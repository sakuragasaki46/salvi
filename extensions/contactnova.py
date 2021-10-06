# (c) 2021 Sakuragasaki46
# See LICENSE for copying info.

'''
Contact Nova extension for Salvi.
'''

from peewee import *
import datetime
from app import _getconf
from flask import Blueprint, request, redirect, render_template, jsonify, abort
from werkzeug.routing import BaseConverter
import csv
import io
import re
import itertools

#### HELPERS ####

class RegExpField(CharField):
    def __init__(self, regex, max_length=255, *args, **kw):
        super().__init__(max_length, *args, **kw)
        self.regex = regex
    def db_value(self, value):
        value = value.strip()
        # XXX %: bug fix for LIKE, but it’s not something regular!
        if not '%' in value and not re.fullmatch(self.regex, value):
            raise IntegrityError("regexp mismatch: {!r}".format(self.regex))
        return value

def now7days():
    return datetime.datetime.now() + datetime.timedelta(days=7)
    
#### DATABASE SCHEMA ####

database = SqliteDatabase(_getconf("config", "database_dir") + '/contactnova.sqlite')

class BaseModel(Model):
    class Meta:
        database = database

ST_UNKNOWN = 0
ST_OK      = 1
ST_ISSUES  = 2

class Contact(BaseModel):
    code = RegExpField(r'[A-Z]\.\d+', 30, unique=True)
    display_name = RegExpField('[A-Za-z0-9_. ]+', 50, index=True)
    status = IntegerField(default=ST_UNKNOWN, index=True)
    issues = CharField(500, default='')
    description = CharField(5000, default='')
    due = DateField(index=True, default=now7days)
    touched = DateTimeField(index=True, default=datetime.datetime.now)
    def status_str(self):
        return {
            1: "task_alt",
            2: "error_outline",
        }.get(self.status, "")
    def __repr__(self):
        return '<{0.__class__.__name__}: {0.code}>'.format(self)
    @classmethod
    def next_code(cls, letter):
        try:
            last_code = Contact.select().where(Contact.code ** (letter + '%')).order_by(Contact.id.desc()).first().code.split('.')
        except (Contact.DoesNotExist, AttributeError):
            last_code = letter, '0'
        code = letter + '.' + str(int(last_code[1]) + 1)
        return code

def init_db():
    database.create_tables([Contact])

def create_cli():
    code = Contact.next_code(input('Code letter:'))
    
    return Contact.create(
        code=code,
        display_name=input('Display name:'),
        due=datetime.datetime.fromisoformat(input('Due date (ISO):')),
        description=input('Description (optional):')
    )

# Helper for command line.
class _CCClass:
    def __init__(self, cb=lambda x:x):
        self.callback = cb
    def __neg__(self):
        return create_cli()
    def __getattr__(self, value):
        code = value[0] + '.' + value[1:]
        try:
            return self.callback(Contact.get(Contact.code == code))
        except Contact.DoesNotExist:
            raise AttributeError(value) from None
    def ok(self):
        def cb(a):
            a.status = 1
            a.save()
            return a
        return self.__class__(cb)
CC = _CCClass()
del _CCClass

#### ROUTE HELPERS ####

class ContactCodeConverter(BaseConverter):
    regex = r'[A-Z]\.\d+'

class ContactMockConverter(BaseConverter):
    regex = r'[A-Z]'

def _register_converters(state):
    state.app.url_map.converters['contactcode'] = ContactCodeConverter
    state.app.url_map.converters['singleletter'] = ContactMockConverter

# Helper for pagination.
def paginate_list(cat, q):
    pageno = int(request.args.get('page', 1))
    return render_template(
        "contactnova/list.html",
        cat=cat,
        count=q.count(),
        people=q.offset(50 * (pageno - 1)).limit(50),
        pageno=pageno
    )

bp = Blueprint('contactnova', __name__,
               url_prefix='/kt')
bp.record_once(_register_converters)

@bp.route('/init-config')
def _init_config():
    init_db()
    return redirect('/kt')

@bp.route('/')
def homepage():
    q = Contact.select().where(Contact.due > datetime.datetime.now()).order_by(Contact.due.desc())
    return paginate_list('All', q)

@bp.route('/expired')
def expired():
    q = Contact.select().where(Contact.due <= datetime.datetime.now()).order_by(Contact.due)
    return paginate_list('Expired', q)

@bp.route('/ok')
def sanecontacts():
    q = Contact.select().where((Contact.due > datetime.datetime.now()) &
                               (Contact.status == ST_OK)).order_by(Contact.due)
    return paginate_list('Sane', q)

@bp.route('/<singleletter:l>')
def singleletter(l):
    q = Contact.select().where(Contact.code ** (l + '%')).order_by(Contact.id)
    return paginate_list('Series {}'.format(l), q)

@bp.route('/<contactcode:code>')
def singlecontact(code):
    try:
        p = Contact.get(Contact.code == code)
    except IntegrityError:
        abort(404)
    return render_template('contactnova/single.html', p=p)
    
@bp.route('/_newcode/<singleletter:l>')
def newcode(l):
    return Contact.next_code(l), {"Content-Type": "text/plain"}

@bp.route('/new', methods=['GET', 'POST'])
def newcontact():
    if request.method == 'POST':
        Contact.create(
            code = Contact.next_code(request.form['letter']),
            display_name = request.form['display_name'],
            status = request.form['status'],
            issues = request.form['issues'],
            description = request.form['description'],
            due = datetime.date.fromisoformat(request.form['due'])
        )
        return redirect(request.form.get('returnto','/kt/'+request.form['letter']))
    return render_template('contactnova/new.html', pl_date = now7days())

@bp.route('/edit/<contactcode:code>', methods=['GET', 'POST'])
def editcontact(code):
    pl = Contact.get(Contact.code == code)
    if request.method == 'POST':
        pl.display_name = request.form['display_name']
        pl.issues = request.form['issues']
        pl.status = request.form['status']
        pl.description = request.form['description']
        pl.due = datetime.date.fromisoformat(request.form['due'])
        pl.touched = datetime.datetime.now()
        pl.save()
        return redirect(request.form.get('returnto','/kt/'+pl.code[0]))
    return render_template('contactnova/new.html', pl = pl)

@bp.route('/_jsoninfo/<float:ts>')
def contact_jsoninfo(ts):
    tse = str(datetime.datetime.fromtimestamp(ts).isoformat(" "))
    ps = Contact.select().where(Contact.touched >= tse)
    return jsonify({
        "ids": [i.code for i in ps],
        "data": [
            {
                'code': i.code,
                'display_name': i.display_name,
                'due': datetime.datetime.fromisoformat(i.due.isoformat()).timestamp(),
                'issues': i.issues,
                'description': i.description,
                'status': i.status
            } for i in ps
        ],
        "status": "ok"
    })
