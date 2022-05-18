# (C) 2020-2021 Sakuragasaki46.
# See LICENSE for copying info.

'''
A simple wiki-like note webapp.

Pages are stored in SQLite databases.
Markdown is used for text formatting.

Application is kept compact, with all its core in a single file.
Extensions are supported (?), kept in extensions/ folder.
'''

#### IMPORTS ####

from flask import (
    Flask, Markup, abort, flash, g, jsonify, make_response, redirect, request,
    render_template, send_from_directory)
from werkzeug.routing import BaseConverter
from peewee import *
import csv, datetime, hashlib, html, importlib, json, markdown, os, random, \
    re, sys, uuid, warnings
from functools import lru_cache, partial
from urllib.parse import quote
from configparser import ConfigParser
try:
    import gzip
except ImportError:
    gzip = None
try:
    from slugify import slugify
except ImportError:
    slugify = None

__version__ = '0.5'

#### CONSTANTS ####

APP_BASE_DIR = os.path.dirname(__file__)

FK = ForeignKeyField

SLUG_RE = r'[a-z0-9]+(?:-[a-z0-9]+)*'
MAGIC_RE = r'\{\{\s*(' + SLUG_RE + ')\s*:\s*(.*?)\s*\}\}'
REDIRECT_RE = r'\{\{\s*redirect\s*:\s*(\d+)\s*\}\}'

upload_types = {'jpeg': 1, 'jpg': 1, 'png': 2}
upload_types_rev = {1: 'jpg', 2: 'png'}

UPLOAD_DIR = APP_BASE_DIR + '/media'
DATABASE_DIR = APP_BASE_DIR + "/database"

#### GENERAL CONFIG ####

DEFAULT_CONF = {
    ('site', 'title'):          'Salvi',
    ('config', 'media_dir'):    APP_BASE_DIR + '/media',
    ('config', 'database_dir'): APP_BASE_DIR + "/database",
}

_cfp = ConfigParser()
if _cfp.read([APP_BASE_DIR + '/site.conf']):
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
    def _getconf(k1, k2, fallback=None, cast=None):
        if fallback is None:
            fallback = DEFAULT_CONF.get((k1, k2))
        return fallback

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


#### MARKDOWN EXTENSIONS ####

class StrikethroughExtension(markdown.extensions.Extension):
    def extendMarkdown(self, md, md_globals):
        postprocessor = StrikethroughPostprocessor(md)
        md.postprocessors.add('strikethrough', postprocessor, '>raw_html')

class StrikethroughPostprocessor(markdown.postprocessors.Postprocessor):
    pattern = re.compile(r"~~(((?!~~).)+)~~", re.DOTALL)

    def run(self, html):
        return re.sub(self.pattern, self.convert, html)

    def convert(self, match):
        return '<del>' + match.group(1) + '</del>'

### XXX it currently only detects spoilers that are not at the beginning of the line. To be fixed.
class SpoilerExtension(markdown.extensions.Extension):
    def extendMarkdown(self, md, md_globals):
        md.inlinePatterns.register(markdown.inlinepatterns.SimpleTagInlineProcessor(r'()>!(.*?)!<', 'span class="spoiler"'), 'spoiler', 14)

#### DATABASE SCHEMA ####

database = SqliteDatabase(_getconf("config", "database_dir") + '/data.sqlite')

class BaseModel(Model):
    class Meta:
        database = database

# Used for PagePolicy
def _passphrase_hash(pp):
    pp_bin = pp.encode('utf-8')
    h = str(len(pp_bin)) + ':' + hashlib.sha256(pp_bin).hexdigest()
    return h

class Page(BaseModel):
    url = CharField(64, unique=True, null=True)
    title = CharField(256, index=True)
    touched = DateTimeField(index=True)
    flags = BitField()
    is_redirect = flags.flag(1)
    is_sync = flags.flag(2)
    @property
    def latest(self):
        if self.revisions:
            return self.revisions.order_by(PageRevision.pub_date.desc())[0]
    def get_url(self):
        return '/' + self.url + '/' if self.url else '/p/{}/'.format(self.id)
    def short_desc(self):
        text = remove_tags(self.latest.text, convert = not _getconf('site', 'simple_remove_tags', False))
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
    def unlock(self, perm, pp, sec):
        ## XX complete later!
        policies = self.policies.where(PagePolicy.type << _makelist(perm))
        if not policies.exists():
            return True
        for policy in policies:
            if policy.verify(pp, sec):
                return True
        return False
    def is_locked(self, perm):
        policies = self.policies.where(PagePolicy.type << _makelist(perm))
        return policies.exists()
    def is_classified(self):
        return self.is_locked(POLICY_CLASSIFY)
    def is_editable(self):
        return not self.is_locked(POLICY_EDIT)
            

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
    def create_content(cls, text, treshold=600, search_dup=True):
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
    user_id = IntegerField(default=0)
    comment = CharField(1024, default='')
    textref = FK(PageText)
    pub_date = DateTimeField(index=True)
    length = IntegerField()
    @property
    def text(self):
        return self.textref.get_content()
    def html(self):
        return md(self.text)
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

# Store keys for PagePolicy.
# Experimental.
class PagePolicyKey(BaseModel):
    passphrase = CharField()
    sec_code = IntegerField()
    class Meta:
        indexes = (
            (('passphrase','sec_code'), True),
        )

    @classmethod
    def create_from_plain(cls, pp, sec):
        PagePolicyKey.create(passphrase=_passphrase_hash(pp), sec_code=sec)
    def verify(self, pp, sec):
        h = _passphrase_hash(pp)
        return self.passphrase == h and self.sec_code == sec

POLICY_ADMIN = 1
POLICY_READ = 2
POLICY_EDIT = 3
POLICY_META = 4
POLICY_CLASSIFY = 5

# Manage policies for pages (e.g., reading or editing).
# Experimental.
class PagePolicy(BaseModel):
    page = FK(Page, backref='policies', index=True, null=True)
    type = IntegerField()
    key = FK(PagePolicyKey, backref='applied_to')
    sitewide = IntegerField(default=0)

    class Meta:
        indexes = (
            (('page', 'key'), True),
        )

# DEPRECATED
# It will be possibly removed in v0.6.
# Use external image URL instead.
class Upload(BaseModel):
    name = CharField(256)
    url_name = CharField(256, null=True)
    filetype = SmallIntegerField()
    filesize = IntegerField()
    upload_date = DateTimeField(index=True)
    md5 = CharField(32, index=True)
    @property
    def filepath(self):
        return '{0}/{1}/{2}{3}.{4}'.format(self.md5[:1], self.md5[:2], self.id, 
            '-' + self.url_name if self.url_name else '', upload_types_rev[self.filetype])
    @property
    def url(self):
        return '/media/' + self.filepath
    def get_content(self, check=True):
        with open(os.path.join(UPLOAD_DIR, self.filepath)) as f:
            content = f.read()
        if check:
            if len(content) != self.filesize:
                raise AssertionError('file is corrupted')
            if hashlib.md5(content).hexdigest() != self.md5:
                raise AssertionError('file is corrupted')
        return content
    @classmethod
    def create_content(cls, name, ext, content):
        ext = ext.lstrip('.')
        if ext not in upload_types:
            raise ValueError('invalid file type')
        filetype = upload_types[ext]
        name = name[:256]
        if slugify:
            url_name = slugify(name)[:256]
        else:
            url_name = None
        filemd5 = hashlib.md5(content).hexdigest()
        basepath = os.path.join(UPLOAD_DIR, filemd5[:1], filemd5[:2])
        if not os.path.exists(basepath):
            os.makedirs(basepath)
        obj = cls.create(
            name=name,
            url_name=url_name,
            filetype=filetype,
            filesize=len(content),
            upload_date=datetime.datetime.now(),
            md5=filemd5
        )
        try:
            with open(os.path.join(basepath, '{0}{1}.{2}'.format(obj.id, 
                    '-' + url_name if url_name else '', upload_types_rev[filetype]
                    )), 'wb') as f:
                f.write(content)
        except OSError:
            cls.delete_by_id(obj.id)
            raise
        return obj

def init_db():
    database.create_tables([Page, PageText, PageRevision, PageTag, PageProperty, PagePolicyKey, PagePolicy, Upload])

#### WIKI SYNTAX ####

def md(text, expand_magic=False, toc=True):
    if expand_magic:
        # DEPRECATED seeking for a better solution.
        warnings.warn('Magic words are no more supported.', DeprecationWarning)
    extensions = ['tables', 'footnotes', 'fenced_code', 'sane_lists', StrikethroughExtension(), SpoilerExtension()]
    if toc:
        extensions.append('toc')
    return markdown.Markdown(extensions=extensions).convert(text)

def remove_tags(text, convert=True, headings=True):
    if headings:
        text = re.sub(r'\#[^\n]*', '', text)
    if convert:
        text = md(text, toc=False)
    return re.sub(r'<.*?>', '', text)

#### I18N ####

lang_poses = {'en': 1, 'en-US': 1, 'it': 2, 'it-IT': 2}

def read_strings():
    with open(APP_BASE_DIR + '/strings.csv', encoding='utf-8') as f:
        return csv.reader(f)

@lru_cache(maxsize=1000)
def get_string(lang, name):
    with open(APP_BASE_DIR + '/strings.csv', encoding='utf-8') as f:
        for line in csv.reader(f):
            if not line[0] or line[0].startswith('#'):
                continue
            if line[0] == name:
                ln = lang_poses[lang]
                if len(line) > ln and line[ln]:
                    return line[ln]
                elif len(line) > 1:
                    return line[1]
    return '(' + name + ')'


#### APPLICATION CONFIG ####

class SlugConverter(BaseConverter):
    regex = SLUG_RE

def is_valid_url(url):
    return re.fullmatch(SLUG_RE, url)

def is_url_available(url):
    return url not in forbidden_urls and not Page.select().where(Page.url == url).exists()

forbidden_urls = [
    'create', 'edit', 'p', 'ajax', 'history', 'manage', 'static', 'media',
    'accounts', 'tags', 'init-config', 'upload', 'upload-info', 'about',
    'stats', 'terms', 'privacy', 'easter', 'search', 'help', 'circles',
    'protect', 'kt', 'embed'
]

app = Flask(__name__)
app.secret_key = 'qrdldCcvamtdcnidmtasegasdsedrdqvtautar'
app.url_map.converters['slug'] = SlugConverter


#### ROUTES ####

@app.before_request
def _before_request():
    for l in request.headers.get('accept-language', 'it,en').split(','):
        if ';' in l:
            l, _ = l.split(';')
            if l in lang_poses:
                lang = l
                break
    else:
        lang = 'en'
    g.lang = lang

@app.context_processor
def _inject_variables():
    return {
        'T': partial(get_string, g.lang),
        'app_name': _getconf('site', 'title'),
        'strong': lambda x:Markup('<strong>{0}</strong>').format(x),
        'app_version': __version__
    }

@app.template_filter()
def linebreaks(text):
    text = html.escape(text)
    text = text.replace("\n\n", '</p><p>').replace('\n', '<br />')
    return Markup(text)

@app.route('/')
def homepage():
    page_limit = _getconf("appearance","items_per_page",20,cast=int)
    return render_template('home.html', new_notes=Page.select()
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
    return render_template('notfound.html'), 404

@app.errorhandler(403)
def error_403(body):
    return render_template('forbidden.html'), 403

@app.errorhandler(500)
def error_400(body):
    return render_template('badrequest.html'), 400

# Middle point during page editing.
def savepoint(form, is_preview=False, pageid=None):
    if is_preview:
        preview = md(form['text'])
    else:
        preview = None
    pl_js_info = dict()
    pl_js_info['editing'] = dict(
        original_text = None, # TODO
        preview_text = form['text'],
        page_id = pageid
    )
    return render_template('edit.html', pl_url=form['url'], pl_title=form['title'], pl_text=form['text'], pl_tags=form['tags'], preview=preview, pl_js_info=pl_js_info)

@app.route('/create/', methods=['GET', 'POST'])
def create():
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
            )
            p.change_tags(p_tags)
        except IntegrityError as e:
            flash('An error occurred while saving this revision: {e}'.format(e=e))
            return savepoint(request.form)
        pr = PageRevision.create(
            page=p,
            user_id=0,
            comment='',
            textref=PageText.create_content(request.form['text']),
            pub_date=datetime.datetime.now(),
            length=len(request.form['text'])
        )
        return redirect(p.get_url())
    return render_template('edit.html', pl_url=request.args.get('url'))

@app.route('/edit/<int:id>/', methods=['GET', 'POST'])
def edit(id):
    p = Page[id]
    if request.method == 'POST':
        if request.form.get('preview'):
            return savepoint(request.form, is_preview=True, pageid=id)
        p_url = request.form['url'] or None
        if p_url:
            if not is_valid_url(p_url):
                flash('Invalid URL. Valid URLs contain only letters, numbers and hyphens.')
                return savepoint(request.form, pageid=id)
            elif not is_url_available(p_url) and p_url != p.url:
                flash('This URL is not available.')
                return savepoint(request.form, pageid=id)
        p_tags = [x.strip().lower().replace(' ', '-').replace('_', '-').lstrip('#')
            for x in request.form.get('tags', '').split(',')]
        p_tags = [x for x in p_tags if x]
        if any(not re.fullmatch(SLUG_RE, x) for x in p_tags):
            flash('Invalid tags text. Tags contain only letters, numbers and hyphens, and are separated by comma.')
            return savepoint(request.form, pageid=id)
        p.url = p_url
        p.title = request.form['title']
        p.touched = datetime.datetime.now()
        p.save()
        p.change_tags(p_tags)
        pr = PageRevision.create(
            page=p,
            user_id=0,
            comment='',
            textref=PageText.create_content(request.form['text']),
            pub_date=datetime.datetime.now(),
            length=len(request.form['text'])
        )
        return redirect(p.get_url())
    return render_template('edit.html', pl_url=p.url, pl_title=p.title, pl_text=p.latest.text, pl_tags=','.join(x.name for x in p.tags))

@app.route("/__sync_start")
def __sync_start():
    if _getconf("sync", "master", "this") == "this":
        abort(403)
    from app_sync import main
    main()
    flash("Successfully synced messages.")
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
    return render_template('view.html', p=p, rev=p.latest)

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
@app.route('/p/most_recent/<int:page>/')
def view_most_recent(page=1):
    general_query = Page.select().order_by(Page.touched.desc())
    return render_template('listrecent.html', notes=general_query.paginate(page),
        page_n=page, total_count=general_query.count(), min=min)

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
    

@app.route('/<slug:name>/')
def view_named(name):
    try:
        p = Page.get(Page.url == name)
    except Page.DoesNotExist:
        abort(404)
    return render_template('view.html', p=p, rev=p.latest)

@app.route('/init-config/tables/')
def init_config_tables():
    init_db()
    flash('Tables successfully created.')
    return redirect('/')

@app.route('/history/<int:id>/')
def history(id):
    try:
        p = Page[id]
    except Page.DoesNotExist:
        abort(404)
    return render_template('history.html', p=p, history=p.revisions.order_by(PageRevision.pub_date.desc()))

@app.route('/history/revision/<int:revisionid>/')
def view_old(revisionid):
    try:
        rev = PageRevision[revisionid]
    except PageRevision.DoesNotExist:
        abort(404)
    p = rev.page
    return render_template('viewold.html', p=p, rev=rev)

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
        return render_template('search.html', q=q, pl_include_tags=include_tags,
            results=query.paginate(1))
    return render_template('search.html', pl_include_tags=True)

@app.route('/tags/<slug:tag>/')
@app.route('/tags/<slug:tag>/<int:page>/')
def listtag(tag, page=1):
    general_query = Page.select().join(PageTag, on=PageTag.page).where(PageTag.name == tag).order_by(Page.touched.desc())
    page_query = general_query.paginate(page)
    return render_template('listtag.html', tagname=tag, tagged_notes=page_query,
        page_n=page, total_count=general_query.count(), min=min)

@app.route('/media/<path:fp>')
def media(fp):
    return send_from_directory(UPLOAD_DIR, fp)

# symbolic route as of v0.5
@app.route('/upload/', methods=['GET'])
def upload():
    return render_template('upload.html')

@app.route('/stats/')
def stats():
    return render_template('stats.html', 
        notes_count=Page.select().count(),
        notes_with_url=Page.select().where(Page.url != None).count(),
        upload_count=Upload.select().count(),
        revision_count=PageRevision.select().count()
    )

@app.route('/accounts/theme-switch')
def theme_switch():
    cook = request.cookies.get('dark')
    resp = make_response(redirect(request.args.get('next', '/')))
    resp.set_cookie('dark', '0' if cook == '1' else '1', max_age=31556952, path='/')
    return resp

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
            return render_template('easter.html')
        return render_template('easter.html', y=y, easter_dates=stash_easter(y))
    else:
        return render_template('easter.html')

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

