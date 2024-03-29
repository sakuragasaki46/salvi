# (C) 2020-2021 Sakuragasaki46.
# See LICENSE for copying info.

'''
A simple wiki-like note webapp.

Pages are stored in SQLite/MySQL databases.
Markdown is used for text formatting.

Application is kept compact, with all its core in a single file.
'''

#### IMPORTS ####

from flask import (
    Flask, abort, flash, g, jsonify, make_response, redirect, request,
    render_template, send_from_directory)
from markupsafe import Markup
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from flask_wtf import CSRFProtect
#from flask_arrest import RestBlueprint, serialize_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.routing import BaseConverter
from peewee import *
from playhouse.db_url import connect as dbconnect
import datetime, hashlib, html, importlib, json, markdown, os, random, \
    re, sys, warnings
from functools import lru_cache, partial
from urllib.parse import quote
from configparser import ConfigParser
import i18n
import gzip
from getpass import getpass
import dotenv

__version__ = '0.9-dev'

#### CONSTANTS ####

APP_BASE_DIR = os.path.dirname(__file__)

FK = ForeignKeyField

SLUG_RE = r'[a-z0-9]+(?:-[a-z0-9]+)*'
ILINK_RE = r'\]\(/(p/\d+|' + SLUG_RE + ')/?\)'
USERNAME_RE = r'[a-z0-9_-]{3,30}'
PING_RE = r'(?<!\w)@(' + USERNAME_RE + r')'

#### GENERAL CONFIG ####

dotenv.load_dotenv(os.path.join(APP_BASE_DIR, '.env'))

CONFIG_FILE = os.getenv('SALVI_CONF', os.path.join(APP_BASE_DIR, 'site.conf'))

# security check: one may specify only configuration files INSIDE
# the code directory.
if not os.path.abspath(CONFIG_FILE).startswith(APP_BASE_DIR):
    raise OSError("Invalid configuration file")

DEFAULT_CONF = {
    ('site', 'title'): os.getenv('APP_NAME', 'Salvi'),
}

_cfp = ConfigParser()
if _cfp.read([CONFIG_FILE]):
    @lru_cache(maxsize=50)
    def _getconf(k1, k2, fallback=None, cast=None):
        if fallback is None:
            fallback = DEFAULT_CONF.get((k1, k2))
        v = _cfp.get(k1, k2, fallback=fallback)
        if cast in (int, float, str):
            try:
                v = cast(v)
            except ValueError:
                v = fallback
        return v
else:
    print('Uh oh, site.conf not found.')
    exit(-1)

#### misc. helpers ####

def _makelist(l):
    if isinstance(l, (str, bytes, bytearray)):
        return [l]
    elif hasattr(l, '__iter__'):
        return list(l)
    elif l:
        return [l]
    else:
        return []

def render_paginated_template(template_name, query_name, **kwargs):
    query = kwargs.pop(query_name)
    page = int(request.args.get('page', 1))
    kwargs[query_name] = query.paginate(page)
    return render_template(
        template_name,
        page_n = page,
        total_count = query.count(),
        **kwargs
    )

#### MARKDOWN EXTENSIONS ####

class StrikethroughExtension(markdown.extensions.Extension):
    def extendMarkdown(self, md, md_globals=None):
        postprocessor = StrikethroughPostprocessor(md)
        md.postprocessors.register(postprocessor, 'strikethrough', 0)

class StrikethroughPostprocessor(markdown.postprocessors.Postprocessor):
    pattern = re.compile(r"~~(((?!~~).)+)~~", re.DOTALL)

    def run(self, html):
        return re.sub(self.pattern, self.convert, html)

    def convert(self, match):
        return '<del>' + match.group(1) + '</del>'

# XXX ugly monkeypatch to make spoilers prevail over blockquotes
from markdown.blockprocessors import BlockQuoteProcessor
BlockQuoteProcessor.RE = re.compile(r'(^|\n)[ ]{0,3}>(?!!)[ ]?(.*)')

### XXX it currently only detects spoilers that are not at the beginning of the line. To be fixed.
class SpoilerExtension(markdown.extensions.Extension):
    def extendMarkdown(self, md, md_globals=None):
        md.inlinePatterns.register(markdown.inlinepatterns.SimpleTagInlineProcessor(r'()>!(.*?)!<', 'span class="spoiler"'), 'spoiler', 14)


#class PingExtension(markdown.extensions.Extension):
#    def extendMarkdown(self, md):
#        pass

#### DATABASE SCHEMA ####

database_url = os.getenv("DATABASE_URL") or _getconf('database', 'url')
if database_url:
    database = dbconnect(database_url)
else:
    print("Database URL required.")
    exit(-1)

class BaseModel(Model):
    class Meta:
        database = database

class User(BaseModel):
    username = CharField(32, unique=True)
    email = CharField(256, null=True)
    password = CharField()
    join_date = DateTimeField(default=datetime.datetime.now)
    karma = IntegerField(default=1)
    privileges = BitField()
    is_admin = privileges.flag(1)
    restrictions = BitField()
    is_disabled = restrictions.flag(1)

    # helpers for flask_login
    @property
    def is_anonymous(self):
        return False
    @property
    def is_active(self):
        return not self.is_disabled
    @property
    def is_authenticated(self):
        return True

    @property
    def groups(self):
        return (
            UserGroup.select().join(UserGroupMembership, on=UserGroupMembership.group)
            .where(UserGroupMembership.user == self)
        )
    
    def get_perms(self):
        if self.is_admin:
            return PERM_ALL

        perm = 0

        for gr in self.groups:
            perm |= gr.permissions
        
        return perm


# page perms (used as bitmasks)
PERM_READ = 1
PERM_EDIT = 2
PERM_CREATE = 4
PERM_SET_URL = 8
PERM_SET_TAGS = 16
PERM_ALL = 31
PERM_LOCK = ~(PERM_EDIT | PERM_CREATE | PERM_SET_URL | PERM_SET_TAGS)

class UserGroup(BaseModel):
    name = CharField(32, unique=True)
    permissions = BitField()
    # Can read pages.
    can_read = permissions.flag(1)
    # Can edit all non-locked pages.
    can_edit = permissions.flag(2)
    # Can create and edit their own pages.
    can_create = permissions.flag(4)
    # Can set page URL.
    can_set_url = permissions.flag(8)
    # Can change page tags.
    can_set_tags = permissions.flag(16)

    @classmethod
    def get_default_group(cls):
        try:
            return cls[1]
        except cls.DoesNotExist:
            return cls.get(cls.name == 'default')

class UserGroupMembership(BaseModel):
    user = ForeignKeyField(User, backref='group_memberships')
    group = ForeignKeyField(UserGroup, backref='user_memberships')
    since = DateTimeField(default=datetime.datetime.now)

    class Meta:
        indexes = (
            (('user', 'group'), True),
        )


class Page(BaseModel):
    url = CharField(64, unique=True, null=True)
    title = CharField(256, index=True)
    touched = DateTimeField(index=True)
    calendar = DateTimeField(index=True, null=True)
    owner = ForeignKeyField(User, null=True)
    flags = BitField()
    is_redirect = flags.flag(1)
    is_sync = flags.flag(2)
    is_math_enabled = flags.flag(4) # legacy, math is no more supported
    is_locked = flags.flag(8)
    is_cw = flags.flag(16)
    @property
    def latest(self):
        if self.revisions:
            return self.revisions.order_by(PageRevision.pub_date.desc())[0]
    def get_url(self):
        return '/' + self.url + '/' if self.url else '/p/{}/'.format(self.id)
    def short_desc(self):
        if self.is_cw:
            return '(Content Warning: we are not allowed to show a description.)'
        full_text = self.latest.text
        text = remove_tags(full_text, convert = not _getconf('appearance', 'simple_remove_tags', False))
        return text[:200] + ('\u2026' if len(text) > 200 else '')
    def change_tags(self, new_tags):
        old_tags = set(x.name for x in self.tags)
        new_tags = set(new_tags)
        PageTag.delete().where((PageTag.page == self) & 
            (PageTag.name << (old_tags - new_tags))).execute()
        for tag in (new_tags - old_tags):
            PageTag.create(page=self, name=tag)
    def js_info(self):
        latest = self.latest
        return dict(
            id=self.id,
            url=self.url,
            title=self.title,
            is_redirect=self.is_redirect,
            touched=self.touched.timestamp(),
            is_editable=self.is_editable(),
            latest=dict(
                id=latest.id if latest else None,
                length=latest.length,
                pub_date=latest.pub_date.timestamp() if latest and latest.pub_date else None
            ),
            tags=[x.name for x in self.tags]
        )
    @property
    def prop(self):
        return PagePropertyDict(self)
    def is_editable(self):
        return self.can_edit(current_user)

    def can_edit(self, user):
        perm = self.get_perms(user)
        return perm & PERM_EDIT or (self.owner == user and perm & PERM_CREATE)
    def is_owned_by(self, user):
        return user.id == self.owner.id

    def get_perms(self, user=None):
        if user is None:
            user = current_user

        if user.is_anonymous:
            return UserGroup.get_default_group().permissions & PERM_LOCK

        if user.is_admin:
            return PERM_ALL

        perm = 0
        # default groups  
        for gr in user.groups:
            perm |= gr.permissions

        # page overrides
        for ov in self.permission_overrides:
            if ov.group in user.groups:
                perm |= ov.permissions

        if self.is_locked and self.owner.id != user.id:
            perm &= PERM_LOCK
        return perm
    
    def seo_keywords(self):
        kw = []
        for tag in self.tags:
            kw.append(tag.name.replace("-", " "))
        for bkl in self.back_links:
            try:
                kw.append(bkl.from_page.title.replace(",", ""))
            except Exception:
                pass
        return ", ".join(kw)
    
    #def ldjson(self):
    #    return {
    #        "@context": "https://www.w3.org/ns/activitystreams",
    #
    #    }


class PageText(BaseModel):
    content = BlobField()
    flags = BitField()
    is_utf8 = flags.flag(1)
    is_gzipped = flags.flag(2)
    def get_content(self):
        c = self.content
        if self.is_gzipped:
            c = gzip.decompress(c)
        if self.is_utf8:
            return c.decode('utf-8')
        else:
            return c.decode('latin-1')
    @classmethod
    def create_content(cls, text, *, treshold=600, search_dup=True):
        c = text.encode('utf-8')
        use_gzip = len(c) > treshold
        if use_gzip and gzip:
            c = gzip.compress(c)
        if search_dup:
            item = cls.get_or_none((cls.content == c) & (cls.is_gzipped == use_gzip))
            if item:
                return item
        return cls.create(
            content=c,
            is_utf8=True,
            is_gzipped=use_gzip
        )
        
class PageRevision(BaseModel):
    page = FK(Page, backref='revisions', index=True)
    user = ForeignKeyField(User, backref='contributions', null=True)
    comment = CharField(1024, default='')
    textref = FK(PageText)
    pub_date = DateTimeField(index=True)
    length = IntegerField()
    @property
    def text(self):
        return self.textref.get_content()
    def html(self):
        return md(self.text)
    def html_and_toc(self):
        return md_and_toc(self.text)
    def human_pub_date(self):
        delta = datetime.datetime.now() - self.pub_date
        T = partial(get_string, g.lang)
        if delta < datetime.timedelta(seconds=60):
            return T('just-now')
        elif delta < datetime.timedelta(seconds=3600):
            return T('n-minutes-ago').format(delta.seconds // 60)
        
        elif delta < datetime.timedelta(days=1):
            return T('n-hours-ago').format(delta.seconds // 3600)
        elif delta < datetime.timedelta(days=15):
            return T('n-days-ago').format(delta.days)
        else:
            return self.pub_date.strftime('%B %-d, %Y')

class PageTag(BaseModel):
    page = FK(Page, backref='tags', index=True)
    name = CharField(64, index=True)
    class Meta:
        indexes = (
            (('page', 'name'), True),
        )
    def popularity(self):
        return PageTag.select().where(PageTag.name == self.name).count()

class PageProperty(BaseModel):
    page = ForeignKeyField(Page, backref='page_meta', index=True)
    key = CharField(64)
    value = CharField(8000)
    class Meta:
        indexes = (
            (('page', 'key'), True),
        )

# currently experimental
class PagePropertyDict(object):
    def __init__(self, page):
        self._page = page
    def items(self):
        for kv in self._page.page_meta:
            yield kv.key, kv.value
    def __len__(self):
        return self._page.page_meta.count()
    def keys(self):
        for kv in self._page.page_meta:
            yield kv.key
    __iter__ = keys
    def __getitem__(self, key):
        try:
            return self._page.page_meta.get(PageProperty.key == key).value
        except PageProperty.DoesNotExist:
            raise KeyError(key)
    def get(self, key, default=None):
        try:
            return self._page.page_meta.get(PageProperty.key == key).value
        except PageProperty.DoesNotExist:
            return default
    def setdefault(self, key, default):
        try:
            return self._page.page_meta.get(PageProperty.key == key).value
        except PageProperty.DoesNotExist:
            self[key] = default
            return default
    def __setitem__(self, key, value):
        if key in self:
            pp = self._page.page_meta.get(PageProperty.key == key)
            pp.value = value
            pp.save()
        else:
            PageProperty.create(page=self._page, key=key, value=value)
    def __delitem__(self, key):
        PageProperty.delete().where((PageProperty.page == self._page) &
            (PageProperty.key == key)).execute()
    def __contains__(self, key):
        return PageProperty.select().where((PageProperty.page == self._page) &
            (PageProperty.key == key)).exists()


# Link table for caching purposes.
class PageLink(BaseModel):
    from_page = FK(Page, backref='forward_links')
    to_page = FK(Page, backref='back_links')

    class Meta:
        indexes = (
            (('from_page', 'to_page'), True),
        )

    @classmethod
    def parse_links(cls, from_page, text, erase=True):
        with database.atomic():
            old_links = list(cls.select().where(cls.from_page == from_page))
            for mo in re.finditer(ILINK_RE, text):
                try:
                    pageurl = mo.group(1)
                    if pageurl.startswith('p/'):
                        to_page = Page[int(pageurl[2:])]
                    else:
                        to_page = Page.get(Page.url == pageurl)
                    
                    linkobj, created = PageLink.get_or_create(
                        from_page = from_page,
                        to_page = to_page)
                    if linkobj in old_links:
                        old_links.remove(linkobj)
                except Exception:
                    continue
            if erase:
                for linkobj in old_links:
                    linkobj.delete_instance()

    # The actual ULTIMATE method to refresh all links
    # To be called from a maintenance script only!
    @classmethod
    def refresh_all_links(cls):
        for p in Page.select():
            cls.parse_links(p, p.latest.text)

class PagePermission(BaseModel):
    page = ForeignKeyField(Page, backref='permission_overrides')
    group = ForeignKeyField(UserGroup, backref='page_permissions')
    permissions = BitField()
    # Can read pages.
    can_read = permissions.flag(1)
    # Can edit all non-locked pages.
    can_edit = permissions.flag(2)
    # Can create and edit their own pages.
    can_create = permissions.flag(4)
    # Can set page URL.
    can_set_url = permissions.flag(8)
    # Can change page tags.
    can_set_tags = permissions.flag(16)

    class Meta:
        indexes = (
            (('page', 'group'), True),
        )

def init_db():
    database.create_tables([
        User, UserGroup, UserGroupMembership,
        Page, PageText, PageRevision, PageTag, PageProperty, PageLink,
        PagePermission
    ])

def init_db_and_create_first_user():
    try:
        User[1]
        UserGroup[1]
    except Exception:
        pass
    else:
        print('Looks like this site is already set up!')
        return
    username = input('Username: ')
    password = getpass('Password: ')
    confirm_password = getpass('Confirm password: ')
    email = input('Email: (optional)') or None
    if not is_username(username):
        print('Invalid username: usernames can contain only letters, numbers, underscores and hyphens.')
        return
    if password != confirm_password:
        print('Passwords do not match.')
        return
    default_permissions = PERM_ALL # all permissions
    if not input('Agree to the Terms of Use?')[0].lower() == 'y':
        print('You must accept Terms in order to register.')
        return
    with database.atomic():
        init_db()
        ua = User.create(
            username = username,
            email = email,
            password = generate_password_hash(password),
            join_date = datetime.datetime.now(),
            is_admin = True
        )
        ug = UserGroup.create(
            name = 'default',
            permissions = int(default_permissions)
        )
        UserGroupMembership.create(
            user = ua,
            group = ug
        )
    print('Installed successfully!')

#### PERMS HELPERS ####

def has_perms(user, flags, page=None):
    if page:
        perm = page.get_perms(user)
    else:
        perm = user.get_perms()
    
    if perm & flags:
        return True
    return False

#### WIKI SYNTAX ####

def md_and_toc(text, toc=True):
    extensions = ['tables', 'footnotes', 'fenced_code', 'sane_lists']
    extension_configs = {}
    if not _getconf('markdown', 'disable_custom_extensions'): 
        extensions.append(StrikethroughExtension())
        extensions.append(SpoilerExtension())
    if toc:
        extensions.append('toc')
    try:
        converter = markdown.Markdown(extensions=extensions, extension_configs=extension_configs)
        if toc:
            return converter.convert(text), converter.toc
        else:
            return converter.convert(text), ''
    except Exception as e:
        return '<p class="error">There was an error during rendering: {e.__class__.__name__}: {e}</p>'.format(e=e), ''

def md(text, toc=True):
    return md_and_toc(text, toc=toc)[0]

def remove_tags(text, convert=True, headings=True):
    if headings:
        text = re.sub(r'\#[^\n]*', '', text)
    if convert:
        text = md(text, toc=False)
    return re.sub(r'<.*?>', '', text)

def is_username(s):
    return re.match('^' + USERNAME_RE + '$', s)

#### I18N ####

i18n.load_path.append(os.path.join(APP_BASE_DIR, 'i18n'))
i18n.set('file_format', 'json')

def get_string(loc, s):
    i18n.set('locale', loc)
    return i18n.t('salvi.' + s)

#### APPLICATION CONFIG ####

class SlugConverter(BaseConverter):
    regex = SLUG_RE

def is_valid_url(url):
    return re.fullmatch(SLUG_RE, url)

def is_url_available(url):
    return url not in forbidden_urls and not Page.select().where(Page.url == url).exists()

forbidden_urls = [
    'about', 'accounts', 'ajax', 'backlinks', 'calendar', 'circles', 'create',
    'easter', 'edit', 'embed', 'group', 'help', 'history', 'init-config', 'kt',
    'manage', 'media', 'p', 'privacy', 'protect', 'rules', 'search', 'static',
    'stats', 'tags', 'terms', 'u', 'upload', 'upload-info'
]

app = Flask(__name__)
app.secret_key = b'\xf3\xa9?\xbee$L\xabA\xd3\r\xa2\x08\xf6\x00%0b\xa9\xfe\x11\x04\xa6\xd8=\xd3\xa2\x00\xb3\xd5;9'
app.url_map.converters['slug'] = SlugConverter

csrf = CSRFProtect(app)
login_manager = LoginManager(app)

login_manager.login_view = 'accounts_login'

#### ROUTES ####

def _get_lang():
    if request.args.get('uselang') is not None:
        lang = request.args['uselang']
    else:
        for l in request.headers.get('accept-language', 'it,en').split(','):
            if ';' in l:
                l, _ = l.split(';')
                lang = l
                break
        else:
            lang = 'en'
    return lang

@app.before_request
def _before_request():
    g.lang = _get_lang()

@app.context_processor
def _inject_variables():
    return {
        'T': partial(get_string, _get_lang()),
        'app_name': os.getenv("APP_NAME") or _getconf('site', 'title'),
        'strong': lambda x:Markup('<strong>{0}</strong>').format(x),
        'app_version': __version__,
        'material_icons_url': _getconf('site', 'material_icons_url'),
        'min': min
    }

@login_manager.user_loader
def _inject_user(userid):
    u = User[userid]
    if not u.is_disabled:
        return u 

@app.template_filter()
def linebreaks(text):
    text = html.escape(text)
    text = text.replace("\n\n", '</p><p>').replace('\n', '<br />')
    return Markup(text)

app.template_filter(name='markdown')(md)

@app.route('/')
def homepage():
    page_limit = _getconf("appearance", "items_per_page", 20, cast=int)
    return render_template('home.jinja2', new_notes=Page.select()
        .order_by(Page.touched.desc()).limit(page_limit))

@app.route('/robots.txt')
def robots():
    return send_from_directory(APP_BASE_DIR, 'robots.txt')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(APP_BASE_DIR, 'favicon.ico')

## error handlers ##

@app.errorhandler(404)
def error_404(body):
    return render_template('notfound.jinja2'), 404

@app.errorhandler(403)
def error_403(body):
    return render_template('forbidden.jinja2'), 403

@app.errorhandler(400)
def error_400(body):
    return render_template('badrequest.jinja2'), 400

@app.errorhandler(500)
def error_500(body):
    try:
        User[1]
    except OperationalError:
        g.need_install = True
    return render_template('internalservererror.jinja2'), 500

# Middle point during page editing.
def savepoint(form, is_preview=False, pageobj=None):
    if is_preview:
        preview = md(form['text'])
    else:
        preview = None
    pl_js_info = dict()
    pl_js_info['editing'] = dict(
        original_text = None, # TODO
        preview_text = form['text'],
        page_id = pageobj.id if pageobj else None
    )
    return render_template(
        'edit.jinja2',
        pl_url=form['url'],
        pl_title=form['title'],
        pl_text=form['text'],
        pl_tags=form['tags'],
        pl_comment=form['comment'],
        pl_is_locked='lockpage' in form,
        pl_owner_is_current_user=pageobj.is_owned_by(current_user) if pageobj else True,
        preview=preview,
        pl_js_info=pl_js_info,
        pl_calendar=('usecalendar' in form) and form['calendar'],
        pl_readonly=not pageobj.can_edit(current_user) if pageobj else False,
        pl_cw=('cw' in form) and form['cw']
    )

@app.route('/create/', methods=['GET', 'POST'])
@login_required
def create():
    if not has_perms(current_user, PERM_CREATE):
        flash("You are not allowed to create pages.")
        abort(403)
    if request.method == 'POST':
        if request.form.get('preview'):
            return savepoint(request.form, is_preview=True)
        p_url = request.form['url'] or None
        if p_url:
            if not is_valid_url(p_url):
                flash('Invalid URL. Valid URLs contain only letters, numbers and hyphens.')
                return savepoint(request.form)
            elif not is_url_available(p_url):
                flash('This URL is not available.')
                return savepoint(request.form)
        p_tags = [x.strip().lower().replace(' ', '-').replace('_', '-').lstrip('#')
            for x in request.form.get('tags', '').split(',') if x]
        if any(not re.fullmatch(SLUG_RE, x) for x in p_tags):
            flash('Invalid tags text. Tags contain only letters, numbers and hyphens, and are separated by comma.')
            return savepoint(request.form)
        try:
            p = Page.create(
                url=p_url,
                title=request.form['title'],
                is_redirect=False,
                touched=datetime.datetime.now(),
                owner_id=current_user.id,
                calendar=datetime.date.fromisoformat(request.form["calendar"]) if 'usecalendar' in request.form else None,
                is_locked = 'lockpage' in request.form,
                is_cw = 'cw' in request.form
            )
            p.change_tags(p_tags)
        except IntegrityError as e:
            flash('An error occurred while saving this revision: {e}'.format(e=e))
            return savepoint(request.form)
        pr = PageRevision.create(
            page=p,
            user_id=p.owner.id,
            comment='',
            textref=PageText.create_content(request.form['text']),
            pub_date=datetime.datetime.now(),
            length=len(request.form['text'])
        )
        PageLink.parse_links(p, request.form['text'])
        return redirect(p.get_url())
    return savepoint({
        "url": request.args.get("url"),
        "title": "",
        "text": "",
        "tags": "",
        "comment": get_string(g.lang, "page-created")
    })

@app.route('/edit/<int:id>/', methods=['GET', 'POST'])
@login_required
def edit(id):
    p = Page[id]
    if request.method == 'POST':
        # check if page is locked first!
        if not p.can_edit(current_user):
            flash('You are trying to edit a locked page!')
            abort(403)

        if request.form.get('preview'):
            return savepoint(request.form, is_preview=True, pageobj=p)
        p_url = request.form['url'] or None
        if p_url:
            if not is_valid_url(p_url):
                flash('Invalid URL. Valid URLs contain only letters, numbers and hyphens.')
                return savepoint(request.form, pageobj=p)
            elif not is_url_available(p_url) and p_url != p.url:
                flash('This URL is not available.')
                return savepoint(request.form, pageobj=p)
        p_tags = [x.strip().lower().replace(' ', '-').replace('_', '-').lstrip('#')
            for x in request.form.get('tags', '').split(',')]
        p_tags = [x for x in p_tags if x]
        if any(not re.fullmatch(SLUG_RE, x) for x in p_tags):
            flash('Invalid tags text. Tags contain only letters, numbers and hyphens, and are separated by comma.')
            return savepoint(request.form, pageobj=p)
        p.url = p_url
        p.title = request.form['title']
        p.touched = datetime.datetime.now()
        p.is_locked = 'lockpage' in request.form
        p.is_cw = 'cw' in request.form
        p.calendar = datetime.date.fromisoformat(request.form["calendar"]) if 'usecalendar' in request.form else None
        p.save()
        p.change_tags(p_tags)
        if request.form['text'] != p.latest.text:
            pr = PageRevision.create(
                page=p,
                user_id=current_user.id,
                comment=request.form["comment"],
                textref=PageText.create_content(request.form['text']),
                pub_date=datetime.datetime.now(),
                length=len(request.form['text'])
            )
            PageLink.parse_links(p, request.form['text'])
        return redirect(p.get_url())
    
    form = {
        "url": p.url,
        "title": p.title,
        "text": p.latest.text,
        "tags": ','.join(x.name for x in p.tags),
        "comment": ""
    }
    if p.is_locked:
        form["lockpage"] = "1"
    if p.calendar:
        form["usecalendar"] = "1"
        try:
            form["calendar"] = p.calendar.isoformat().split("T")[0]
        except Exception:
            form["calendar"] = p.calendar
    
    return savepoint(form, pageobj=p)

@app.route("/__sync_start")
def __sync_start():
    flash("Sync is unavailable. Please import and export pages manually.")
    return redirect("/")

@app.route('/_jsoninfo/<int:id>', methods=['GET', 'POST'])
def page_jsoninfo(id):
    try:
        p = Page[id]
    except Page.DoesNotExist:
        return jsonify({'status':'fail'}), 404
    j = p.js_info()
    j["status"] = "ok"
    if request.method == "POST":
        j["text"] = p.latest.text
    return jsonify(j)

@app.route("/_jsoninfo/changed/<float:ts>")
def jsoninfo_changed(ts):
    tse = str(datetime.datetime.fromtimestamp(ts).isoformat(" "))
    ps = Page.select().where(Page.touched >= tse)
    return jsonify({
        "ids": [i.id for i in ps],
        "status": "ok"
    })

    
@app.route('/p/<int:id>/')
def view_unnamed(id):
    try:
        p = Page[id]
    except Page.DoesNotExist:
        abort(404)
    if p.url:
        if p.url not in forbidden_urls:
            return redirect(p.get_url())
        else:
            flash('The URL of this page is a reserved URL. Please change it.')
    return render_template('view.jinja2', p=p, rev=p.latest)

@app.route('/embed/<int:id>/')
def embed_view(id):
    try:
        p = Page[id]
    except Page.DoesNotExist:
        return "", 404
    rev = p.latest
    return "<h1>{0}</h1><div class=\"inner-content\">{1}</div>".format(
        html.escape(p.title), rev.html())

@app.route('/p/most_recent/')
def view_most_recent():
    general_query = Page.select().order_by(Page.touched.desc())
    return render_paginated_template('listrecent.jinja2', 'notes', notes=general_query)

@app.route('/p/random/')
def view_random():
    page = None
    if Page.select().count() < 2:
        flash('Too few pages in this site.')
        abort(404)
    while not page:
        try:
            page = Page[random.randint(1, Page.select().count())]
        except Page.DoesNotExist:
            continue
    return redirect(page.get_url())

@app.route('/p/leaderboard/')
def page_leaderboard():
    headers = {
        'Cache-Control': 'max-age=180, stale-while-revalidate=1800'
    }

    pages = []
    for p in Page.select():
        score = (p.latest.length >> 10) + p.forward_links.count() + p.back_links.count()
        pages.append((p, score, p.back_links.count(), p.forward_links.count(), p.latest.length))
    pages.sort(key = lambda x: (x[1], x[2], x[4], x[3]), reverse = True)
        
    return render_template('leaderboard.jinja2', pages=pages), headers

@app.route('/<slug:name>/')
def view_named(name):
    try:
        p = Page.get(Page.url == name)
    except Page.DoesNotExist:
        abort(404)
    return render_template('view.jinja2', p=p, rev=p.latest)

@app.route('/history/<int:id>/')
def history(id):
    try:
        p = Page[id]
    except Page.DoesNotExist:
        abort(404)
    return render_template('history.jinja2', p=p, history=p.revisions.order_by(PageRevision.pub_date.desc()))

@app.route('/u/<username>/')
def contributions_legacy_url(username):
    return redirect(f'/@{username}/')

@app.route('/@<username>/')
def contributions(username):
    try:
        user = User.get(User.username == username)
    except User.DoesNotExist:
        abort(404)
    contributions = user.contributions.order_by(PageRevision.pub_date.desc())
    return render_paginated_template('contributions.jinja2',
        "contributions",
        u=user, 
        contributions=contributions,
    )

def _advance_calendar(date, offset=0):
    if offset == -2:
        return datetime.date(date.year - 1, date.month, 1)
    elif offset == -1:
        return datetime.date(date.year, date.month - 1, 1) if date.month > 1 else datetime.date(date.year - 1, 12, 1)
    elif offset == 1:
        return datetime.date(date.year, date.month + 1, 1) if date.month < 12 else datetime.date(date.year + 1, 1, 1)
    elif offset == 2:
        return datetime.date(date.year + 1, date.month, 1)
    else:
        return date

@app.route('/calendar/')
def calendar_view():
    now = datetime.datetime.now()
    return render_template('calendar.jinja2', now=now,
        from_year=int(request.args.get('from_year', now.year - 12)),
        till_year=int(request.args.get('till_year', now.year + 5))
    )

@app.route('/calendar/<int:y>/<int:m>')
def calendar_month(y, m):
    notes = Page.select().where(
        (datetime.date(y, m, 1) <= Page.calendar) &
        (Page.calendar < datetime.date(y+1 if m==12 else y, 1 if m==12 else m+1, 1))
    ).order_by(Page.calendar)

    #toc_q = Page.select(fn.Month(Page.calendar).alias('month'), fn.Count(Page.id).alias('n_notes')).where(
    #    (datetime.date(y, 1, 1) <= Page.calendar) &
    #    (Page.calendar < datetime.date(y+1, 1, 1))
    #).group_by()
    toc = {}
    #for i in toc_q:
    #    toc[i.month] = i.n_notes

    return render_paginated_template('month.jinja2', "notes", d=datetime.date(y, m, 1), notes=notes, advance_calendar=_advance_calendar, toc=toc)

@app.route('/history/revision/<int:revisionid>/')
def view_old(revisionid):
    try:
        rev = PageRevision[revisionid]
    except PageRevision.DoesNotExist:
        abort(404)
    p = rev.page
    return render_template('viewold.jinja2', p=p, rev=rev)

@app.route('/backlinks/<int:id>/')
def backlinks(id):
    try:
        p = Page[id]
    except Page.DoesNotExist:
        abort(404)
    return render_template('backlinks.jinja2', p=p, backlinks=Page.select().join(PageLink, on=PageLink.to_page).where(PageLink.from_page == p))

@app.route('/search/', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        q = request.form['q']
        include_tags = bool(request.form.get('include-tags'))
        query = Page.select().where(Page.title ** ('%' + q + '%'))
        if include_tags:
            query |= Page.select().join(PageTag, on=PageTag.page
                ).where(PageTag.name ** ('%' + q + '%'))
        query = query.order_by(Page.touched.desc())
        return render_template('search.jinja2', q=q, pl_include_tags=include_tags,
            results=query.paginate(1))
    return render_template('search.jinja2', pl_include_tags=True)

@app.route('/tags/<slug:tag>/')
def listtag(tag):
    general_query = Page.select().join(PageTag, on=PageTag.page).where(PageTag.name == tag).order_by(Page.touched.desc())
    return render_paginated_template('listtag.jinja2', "tagged_notes", tagname=tag, tagged_notes=general_query)


# symbolic route as of v0.5
@app.route('/upload/', methods=['GET'])
def upload():
    return render_template('upload.jinja2')

@app.route('/stats/')
def stats():
    return render_template('stats.jinja2', 
        notes_count=Page.select().count(),
        notes_with_url=Page.select().where(Page.url != None).count(),
        revision_count=PageRevision.select().count(),
        users_count = User.select().count(),
        groups_count = UserGroup.select().count()
    )

## account management ##

@app.route('/accounts/theme-switch')
def theme_switch():
    cook = request.cookies.get('dark')
    resp = make_response(redirect(request.args.get('next', '/')))
    resp.set_cookie('dark', '0' if cook == '1' else '1', max_age=31556952, path='/')
    return resp

@app.route('/accounts/login/', methods=['GET','POST'])
def accounts_login():
    if current_user.is_authenticated:
        return redirect(request.args.get('next', '/'))
    if request.method == 'POST':
        try:
            username = request.form['username']
            user = User.get(User.username == username)
            if not check_password_hash(user.password, request.form['password']):
                flash('Invalid username or password.')
                return render_template('login.jinja2')
        except User.DoesNotExist:
            flash('Invalid username or password.')
        else:
            if user.is_disabled:
                flash("Your account is disabled.")
                return render_template("login.jinja2")

            remember_for = int(request.form['remember'])
            if remember_for > 0:
                login_user(user, remember=True,
                duration=datetime.timedelta(days=remember_for))
            else:
                login_user(user)
            return redirect(request.args.get('next', '/'))
    return render_template('login.jinja2')

@app.route('/accounts/register/', methods=['GET','POST'])
def accounts_register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if not is_username(username):
            flash('Invalid username: usernames can contain only letters, numbers, underscores and hyphens.')
            return render_template('register.jinja2')
        if request.form['password'] != request.form['confirm_password']:
            flash('Passwords do not match.')
            return render_template('register.jinja2')
        if not request.form['legal']:
            flash('You must accept Terms in order to register.')
            return render_template('register.jinja2')
        try:
            with database.atomic():
                u = User.create(
                    username = username,
                    email = request.form.get('email'),
                    password = generate_password_hash(password),
                    join_date = datetime.datetime.now()
                )
                UserGroupMembership.create(
                    user = u,
                    group = UserGroup.get_default_group()
                )
            
            login_user(u)
            return redirect(request.args.get('next', '/'))
        except IntegrityError:
            flash('Username taken')
    return render_template('register.jinja2')

@app.route('/accounts/logout/')
def accounts_logout():
    logout_user()
    return redirect(request.args.get('next', '/'))

## easter egg (lol) ##

MNeaster = {
    15: (22, 2), 16: (22, 2), 17: (23, 3), 18: (23, 4), 19: (24, 5), 20: (24, 5),
    21: (24, 6), 22: (25, 0), 23: (26, 1), 24: (25, 1)}

def calculate_easter(y):
    a, b, c = y % 19, y % 4, y % 7
    M, N = (15, 6) if y < 1583 else MNeaster[y // 100]
    d = (19 * a + M) % 30
    e = (2 * b + 4 * c + 6 * d + N) % 7
    if d + e < 10:
        return datetime.date(y, 3, d + e + 22)
    else:
        day = d + e - 9
        if day == 26:
            day = 19
        elif day == 25 and d == 28 and e == 6 and a > 10:
            day = 18
        return datetime.date(y, 4, day)

def stash_easter(y):
    easter = calculate_easter(y)
    natale = datetime.date(y, 12, 25)
    avvento1 = natale - datetime.timedelta(days=22 + natale.weekday())
    return dict(
        easter = easter,
        ceneri = easter - datetime.timedelta(days=47),
        ascensione = easter + datetime.timedelta(days=42),
        pentecoste = easter + datetime.timedelta(days=49),
        avvento1 = avvento1
    )

@app.route('/easter/')
@app.route('/easter/<int:y>/')
def easter_y(y=None):
    if 'y' in request.args:
        return redirect('/easter/' + request.args['y'] + '/')
    if y:
        if y > 2499:
            flash('Years above 2500 A.D. are currently not supported.')
            return render_template('easter.jinja2')
        return render_template('easter.jinja2', y=y, easter_dates=stash_easter(y))
    else:
        return render_template('easter.jinja2')

## administration ##

@app.route('/manage/')
def manage_main():
    return render_template('administration.jinja2')

## import / export ##

class Exporter(object):
    def __init__(self):
        self.root = {'pages': [], 'users': {}}
    def add_page(self, p, include_history=True, include_users=False):
        pobj = {}
        pobj['title'] = p.title
        pobj['url'] = p.url
        pobj['tags'] = [tag.name for tag in p.tags]
        pobj['calendar'] = p.calendar.isoformat("T") if p.calendar else None
        pobj['flags'] = p.flags
        if include_users:
            pobj['owner'] = p.owner_id
        hist = []
        for rev in (p.revisions if include_history else [p.latest]):
            revobj = {}
            revobj['text'] = rev.text
            revobj['timestamp'] = rev.pub_date.timestamp()
            if include_users:
                revobj['user'] = rev.user_id
                if rev.user_id not in self.root['users']:
                    self.root['users'][rev.user_id] = rev.user_info()
            else:
                revobj['user'] = None
            revobj['comment'] = rev.comment
            revobj['length'] = rev.length
            hist.append(revobj)
        pobj['history'] = hist
        self.root['pages'].append(pobj)
    def add_page_list(self, pl, include_history=True, include_users=False):
        for p in pl:
            self.add_page(p, include_history=include_history, include_users=include_users)
    def export(self):
        return json.dumps(self.root)

class Importer(object):
    def __init__(self, dump, *, overwrite_urls = True):
        self.root = json.loads(dump)
        self.owner = None
        self.overwrite_urls = overwrite_urls
    def claim(self, owner):
        self.owner = owner
    def execute(self):
        no_pages = 0
        no_revs = 0
        for pobj in self.root['pages']:
            purl = pobj.get("url")
            try:
                if purl:
                    try:
                        p2 = Page.get(Page.url == purl)
                        p2.url = None
                        p2.save()
                    except Page.DoesNotExist:
                        pass

                p = Page.create(
                    url = purl if self.overwrite_urls else None,
                    title = pobj['title'],
                    calendar = datetime.datetime.fromisoformat(pobj["calendar"]) if 'calendar' in pobj else None,
                    owner = self.owner.id,
                    flags = pobj.get('flags'),
                    touched = datetime.datetime.now()
                )
                p.change_tags(pobj.get('tags'))
                no_pages += 1

                for revobj in pobj['history']:
                    textref = PageText.create_content(
                        revobj['text']
                    )

                    rev = PageRevision.create(
                        page = p,
                        user_id = self.owner.id,
                        textref = textref,
                        comment = revobj.get('comment'),
                        pub_date = datetime.datetime.fromtimestamp(revobj['timestamp']),
                        length = revobj['length']
                    )
                    no_revs += 1
            except Exception as e:
                sys.excepthook(*sys.exc_info())
                continue
        return no_pages, no_revs

@app.route('/manage/export/', methods=['GET', 'POST'])
def exportpages():
    if request.method == 'POST':
        raw_list = request.form['export-list']
        q_list = []
        for item in raw_list.split('\n'):
            item = item.strip()
            if len(item) < 2:
                continue
            if item.startswith('+'):
                q_list.append(Page.select().where(Page.id == item[1:]))
            elif item.startswith('#'):
                q_list.append(Page.select().join(PageTag, on=PageTag.page).where(PageTag.name == item[1:]))
            elif item.startswith('/'):
                q_list.append(Page.select().where(Page.url == item[1:].rstrip('/')))
            else:
                q_list.append(Page.select().where(Page.title == item)) 
        if not q_list:
            flash('Failed to export pages: The list is empty!')
            return render_template('exportpages.jinja2')
        query = q_list.pop(0)
        while q_list:
            query |= q_list.pop(0)
        e = Exporter()
        e.add_page_list(query, include_history='history' in request.form)
        return e.export(), {'Content-Type': 'application/json', 'Content-Disposition': 'attachment; ' + 
            'filename=export-{}.json'.format(datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))}
    return render_template('exportpages.jinja2')

@app.route('/manage/import/', methods=['GET', 'POST'])
@login_required
def importpages():
    if request.method == 'POST':
        if current_user.is_admin:
            f = request.files['import']
            overwrite_urls = request.form.get('ovwurls')
            im = Importer(f.read(), overwrite_urls=overwrite_urls)
            im.claim(current_user)
            res = im.execute()
            flash('Imported successfully {} pages and {} revisions'.format(*res))
        else:
            flash('Pages can be imported by Administrators only!')
    return render_template('importpages.jinja2')

@app.route('/manage/accounts/', methods=['GET', 'POST'])
@login_required
def manage_accounts():
    users = User.select().order_by(User.join_date.desc())
    page = int(request.args.get('page', 1))
    if request.method == 'POST':
        if current_user.is_admin:
            action = request.form.get("action")
            userids = []
            if action == "disable":
                for key in request.form.keys():
                    if key.startswith("u") and key[1:].isdigit():
                        userids.append(int(key[1:]))
                uu = 0
                for uid in userids:
                    try:
                        u = User[uid]
                    except User.DoesNotExist:
                        continue
                    u.is_disabled = not u.is_disabled
                    u.save()
                    uu += 1
                flash(f"Successfully disabled {uu} users!")
            else:
                flash("Unknown action")
        else:
            flash('Operation not permitted!')
    return render_paginated_template('manageaccounts.jinja2', 'users', users=users)

## terms / privacy ##

@app.route('/terms/')
def terms():
    return render_template('terms.jinja2')

@app.route('/privacy/')
def privacy():
    return render_template('privacy.jinja2')

@app.route('/rules/')
def rules():
    return render_template('rules.jinja2')

#### EXTENSIONS ####

active_extensions = []

_i = 1
_extension_name = _getconf('extensions', 'ext.{}'.format(_i))
while _extension_name:
    active_extensions.append(_extension_name)
    _i += 1
    _extension_name = _getconf('extensions', 'ext.{}'.format(_i))

for ext in active_extensions:
    try:
        bp = importlib.import_module('extensions.' + ext).bp
        app.register_blueprint(bp)
    except Exception:
        sys.stderr.write('Extension not loaded: ' + ext + '\n')
        sys.excepthook(*sys.exc_info())

