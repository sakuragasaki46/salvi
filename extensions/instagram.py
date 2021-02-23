from flask import Blueprint, render_template
from peewee import *
import instagram_private_api, json, os, sys, random, codecs

database = SqliteDatabase('instagram.sqlite')

class BaseModel(Model):
    class Meta:
        database = database

class InstagramProfile(BaseModel):
    p_id = IntegerField()
    p_username = CharField(30)
    p_full_name = CharField(30)
    p_biography = CharField(150)
    posts_count = IntegerField()
    followers_count = IntegerField()
    following_count = IntegerField()
    flags = BitField()
    pub_date = DateTimeField()
    is_verified = flags.flag(1)
    is_private = flags.flag(2)

class InstagramMedia(BaseModel):
    user = IntegerField()
    pub_date = DateTimeField()
    media_url = TextField()
    description = CharField(2200)

def init_db():
    database.create_tables([InstagramProfile, InstagramMedia])

def bytes_to_json(python_object):
    if isinstance(python_object, bytes):
        return {'__class__': 'bytes',
                '__value__': codecs.encode(python_object, 'base64').decode()}
    raise TypeError(repr(python_object) + ' is not JSON serializable')

def bytes_from_json(json_object):
    if '__class__' in json_object and json_object['__class__'] == 'bytes':
        return codecs.decode(json_object['__value__'].encode(), 'base64')
    return json_object

SETTINGS_PATH = 'ig_api_settings'

def load_settings(username):
    with open(os.path.join(SETTINGS_PATH, username + '.json')) as f:
        settings = json.load(f, object_hook=bytes_from_json)
    return settings

def save_settings(username, settings):
    with open(os.path.join(SETTINGS_PATH, username + '.json'), 'w') as f:
        json.dump(settings, f, default=bytes_to_json)

CLIENTS = []

def load_clients():
    try:
        with open(os.path.join(SETTINGS_PATH, 'config.txt')) as f:
            conf = f.read()
    except OSError:
        print('Config file not found.')
        return
    for up in conf.split('\n'):
        try:
            up = up.split('#')[0].strip()
            if not up:
                continue
            username, password = up.split(':')
            try:
                settings = load_settings(username)
            except Exception:
                settings = None
            try:
                if settings:
                    device_id = settings.get('device_id')
                    api = instagram_private_api.Client(
                        username, password,
                        settings=settings
                    )
                else:
                    api = instagram_private_api.Client(
                        username, password,
                        on_login=lambda x: save_settings(username, x.settings)
                    )
            except (instagram_private_api.ClientCookieExpiredError,
                    instagram_private_api.ClientLoginRequiredError) as e:
                api = instagram_private_api.Client(
                    username, password,
                    device_id=device_id,
                    on_login=lambda x: save_settings(username, x.settings)
                )
            CLIENTS.append(api)
        except Exception:
            sys.excepthook(*sys.exc_info())
            continue

def make_request(method_name, *args, **kwargs):
    exc = None
    usable_clients = list(range(len(CLIENTS)))
    while usable_clients:
        ci = random.choice(usable_clients)
        client = CLIENTS[ci]
        usable_clients.remove(ci)
        try:
            method = getattr(client, method_name)
        except AttributeError:
            raise ValueError('client has no method called {!r}'.format(method_name))
        if not callable(method):
            raise ValueError('client has no method called {!r}'.format(method_name))
        try:
            return method(*args, **kwargs)
        except Exception as e:
            exc = e
    if exc:
        raise exc
    else:
        raise RuntimeError('no active clients')

N_FORCE = 0
N_FALLBACK_CACHE = 1
N_PREFER_CACHE = 2
N_OFFLINE = 3

def choose_method(online, offline, network):
    if network == N_FORCE:
        return online()
    elif network == N_FALLBACK_CACHE:
        try:
            return online()
        except Exception:
            return offline()
    elif network == N_PREFER_CACHE:
        try:
            return offline()
        except Exception:
            return online()
    elif network == N_OFFLINE:
        return offline()

def get_profile_info(username_or_id, network=N_FALLBACK_CACHE):
    if isinstance(username_or_id, str):
        username, userid = username_or_id, None
    elif isinstance(username_or_id, int):
        username, userid = None, username_or_id
    else:
        raise TypeError('invalid username or id')
    def online():
        if userid:
            data = make_request('user_info', userid)
        else:
            data = make_request('username_info', username)
        return InstagramProfile.create(
            p_id = data['user']['pk'],
            p_username = data['user']['username'],
            p_full_name = data['user']['full_name'],
            p_biography = data['user']['biography'],
            posts_count = data['user']['media_count'],
            followers_count = data['user']['follower_count'],
            following_count = data['user']['following_count'],
            is_verified = data['user']['is_verified'],
            is_private = data['user']['is_private'],
            pub_date = datetime.datetime.now()
        )
    def offline():
        if userid:
            q = InstagramProfile.select().where(InstagramProfile.p_id == userid)
        else:
            q = InstagramProfile.select().where(InstagramProfile.p_username == username)
        return q.order_by(InstagramProfile.pub_date.desc())[0]
    return choose_method(online, offline, network)

load_clients()
