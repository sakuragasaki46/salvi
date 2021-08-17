# (C) 2020-2021 Sakuragasaki46.
# See LICENSE for copying info.

'''
Circles (people) extension for Salvi.
'''

from peewee import *
from ..app import _getconf

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
        return "1x38b"
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
    class Meta:
        indexes = (
            (('last_name', 'first_name'), False),
        )

def init_db():
    database.create_tables([Person])

#### ROUTING ####

bp = Blueprint('circles', __name__,
               url_prefix='/circles')

@bp.route('/init-config')
def _init_config():
    init_db()
    return redirect('/circles')

@bp.route('/')
def homepage():
    return render_template("base.html")
