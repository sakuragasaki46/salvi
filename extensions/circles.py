# (C) 2020-2021 Sakuragasaki46.
# See LICENSE for copying info.

'''
Circles (people) extension for Salvi.
'''

from peewee import *
import datetime
from app import _getconf
from flask import Blueprint, request, redirect, render_template
from werkzeug.routing import BaseConverter
import csv
import io
import itertools

#### HELPERS ####

def _getmbt(s):
    s = s.upper()
    try:
        return 16 + (
            dict(I=0, E=8)[s[0]] |
            dict(N=0, S=4)[s[1]] |
            dict(T=0, F=2)[s[2]] |
            dict(J=0, P=1)[s[3]]
        )
    except Exception:
        return 2
    

def _putmbt(s):
    if s & 16 == 0:
        return "1x38B"
    return ''.join((
        'IE'[(s & 8) >> 3],
        'NS'[(s & 4) >> 2],
        'TF'[(s & 2) >> 1],
        'JP'[s & 1]
    ))    



#### DATABASE SCHEMA ####

database = SqliteDatabase(_getconf("config", "database_dir") + '/circles.sqlite')

class BaseModel(Model):
    class Meta:
        database = database

class MbTypeField(Field):
    field_type = 'integer'

    def db_value(self, value):
        if isinstance(value, int):
            return value
        return _getmbt(value)
    def python_value(self, value):
        return _putmbt(value)
    
ST_ORANGE = 0
ST_YELLOW = 1
ST_GREEN = 2
ST_RED = -1

class Person(BaseModel):
    code = IntegerField(primary_key=True)
    display_name = CharField(256)
    first_name = CharField(128, null=True)
    last_name = CharField(128, null=True)
    circle = IntegerField(default=7, index=True)
    status = IntegerField(default=ST_ORANGE, index=True)
    type = MbTypeField(default=0, index=True)
    area = IntegerField(default=0, index=True)
    touched = DateTimeField(default=datetime.datetime.now)
    class Meta:
        indexes = (
            (('last_name', 'first_name'), False),
        )

def init_db():
    database.create_tables([Person])

def add_from_csv(s):
    f = io.StringIO()
    f.write(s)
    f.seek(0)
    rd = csv.reader(f)
    for line in rd:
        code = line[0]
        if not code.isdigit():
            continue
        names = line[1:4]
        while len(names) < 3:
            names.append('')
        if not names[2]:
            names[2] = names[0] + " " + names[1]
        type_ = line[4] if len(line) > 4 else 0
        try:
            p = Person[code]
        except Person.DoesNotExist:
            p = Person.create(
                code = code,
                display_name = names[2],
                first_name = names[0],
                last_name = names[1],
                type = type_
            )
        else:
            p.touched = datetime.datetime.now()
            p.first_name, p.last_name, p.display_name = names
            p.type = type_ or p.type
            p.save()
    
#### ROUTING ####

class MbTypeConverter(BaseConverter):
    regex = '[IE][NS][TF][JP]|[ie][ns][tf][jp]'
    def to_python(self, value):
        return value.upper()
    def to_url(self, value):
        return value.lower()

class StatusColorConverter(BaseConverter):
    regex = 'red|yellow|green|orange'
    def to_python(self, value):
        if value == 'red':
            return -1
        return ['orange', 'yellow', 'green'].index(value)
    def to_url(self, value):
        return ['orange', 'yellow', 'green', ..., 'red'][value]

def _register_converters(state):
    state.app.url_map.converters['mbtype'] = MbTypeConverter
    state.app.url_map.converters['statuscolor'] = StatusColorConverter

bp = Blueprint('circles', __name__,
               url_prefix='/circles')
bp.record_once(_register_converters)

@bp.route('/init-config')
def _init_config():
    init_db()
    return redirect('/circles')

@bp.route('/new', methods=['GET', 'POST'])
def add_new():
    if request.method == 'POST':
        p = Person.create(
            code = request.form["code"],
            display_name = request.form["display_name"],
            first_name = request.form["first_name"],
            last_name = request.form["last_name"],
            type = request.form["type"],
            status = int(request.form.get('status', 0))
        )
        return redirect("/circles")
    return render_template("circles/add.html")

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_detail(id):
    p = Person[id]
    if request.method == 'POST':
        p.touched = datetime.datetime.now()
        p.first_name = request.form['first_name']
        p.last_name = request.form['last_name']
        p.display_name = request.form['display_name']
        p.status = int(request.form.get('status', 0))
        p.type = request.form["type"]
        p.area = request.form['area']
        p.save()
        return redirect(request.form['returnto'])
    return render_template("circles/add.html", pl=p, returnto=request.headers.get('Referer', '/circles'))

@bp.route('/csv', methods=['GET', 'POST'])
def add_csv():
    if request.method == 'POST' and request.form.get('consent') == 'y':
        add_from_csv(request.form['text'])
        return redirect('/circles')
    return render_template("circles/csv.html")

# Helper for pagination.
def paginate_list(cat, q):
    pageno = int(request.args.get('page', 1))
    return render_template(
        "circles/list.html",
        cat=cat,
        count=q.count(),
        people=q.offset(50 * (pageno - 1)).limit(50),
        pageno=pageno
    )

@bp.route('/')
def homepage():
    q = Person.select().order_by(Person.touched.desc())
    return paginate_list('all', q)


@bp.route('/<mbtype:typ>')
def typelist(typ):
    q = Person.select().where(Person.type == typ).order_by(Person.touched.desc())
    return paginate_list(typ, q)

@bp.route('/<statuscolor:typ>')
def statuslist(typ):
    q = Person.select().where(Person.status == typ).order_by(Person.touched.desc())
    return paginate_list(['Orange', 'Yellow', 'Green', ..., 'Red'][typ], q)

@bp.route('/area-<int:a>')
def arealist(a):
    q = Person.select().where(Person.area == a).order_by(Person.status.desc(), Person.touched.desc())
    return paginate_list('Area {}'.format(a), q)

@bp.route('/no-area')
def noarealist():
    q = Person.select().where(Person.area == 0).order_by(Person.touched.desc())
    return paginate_list('Unassigned area', q)

@bp.route("/stats")
def stats():
    bq = Person.select()
    return render_template(
        "circles/stats.html",
        count=bq.count(),
        typed_count={
            ''.join(x) : bq.where(Person.type == ''.join(x)).count()
            for x in itertools.product('IE', 'NS', 'TF', 'JP')
        },
        status_count={
            'Red': bq.where(Person.status == -1).count(),
            'Orange': bq.where(Person.status == 0).count(),
            'Yellow': bq.where(Person.status == 1).count(),
            'Green': bq.where(Person.status == 2).count()
        },
        area_count={
            k: bq.where(Person.area == k).count()
            for k in range(1, 13)
        },
        no_area_count=bq.where(Person.area == None).count()
    )
