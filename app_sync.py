"""
Helper module for sync.

(c) 2021 Sakuragasaki46.
"""

import datetime, time
import requests
import sys, os
from configparser import ConfigParser
from app import Page, PageRevision, PageText
from peewee import IntegrityError
from functools import lru_cache

## CONSTANTS ##

APP_BASE_DIR = os.path.dirname(__file__)

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
    def _getconf(k1, k2, fallback=None):
        if fallback is None:
            fallback = DEFAULT_CONF.get((k1, k2))
        v = _cfp.get(k1, k2, fallback=fallback)
        return v
else:
    def _getconf(k1, k2, fallback=None):
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

#### REQUESTS ####

def fetch_updated_ids(baseurl):
    try:
        with open(_getconf("config", "database_dir") + "/latest_sync") as f:
            last_sync = float(f.read().rstrip("\n"))
    except (OSError, ValueError):
        last_sync = 946681200.0  # Jan 1, 2000
    r = requests.get(baseurl + "/_jsoninfo/changed/{ts}".format(ts=last_sync))
    if r.status_code >= 400:
        raise RuntimeError("sync unavailable")
    return r.json()["ids"]

def update_page(p, pageinfo):
    p.touched = datetime.datetime.fromtimestamp(pageinfo["touched"])
    p.url = pageinfo["url"]
    p.title = pageinfo["title"]
    p.save()
    p.change_tags(pageinfo["tags"])
    assert len(pageinfo["text"]) == pageinfo["latest"]["length"]
    pr = PageRevision.create(
        page=p,
        user_id=0,
        comment='',
        textref=PageText.create_content(pageinfo['text']),
        pub_date=datetime.datetime.fromtimestamp(pageinfo["latest"]["pub_date"]),
        length=pageinfo["latest"]["length"]
    )

#### MAIN ####

def main():
    baseurl = _getconf("sync", "master", "this")
    if baseurl == "this":
        print("unsyncable: master", file=sys.stderr)
        return
    if not baseurl.startswith(("http:", "https:")):
        print("unsyncable: invalid url", repr(baseurl), file=sys.stderr)
        return
    passed, failed = 0, 0
    for i in fetch_updated_ids(baseurl):
        pageinfo_r = requests.post(baseurl + "/_jsoninfo/{i}".format(i=i))
        if pageinfo_r.status_code >= 400:
            print("\x1b[31mSkipping {i}: HTTP {s}\x1b[0m".format(i=i, s=pageinfo_r.status_code))
            failed += 1
            continue
        pageinfo = pageinfo_r.json()
        try:
            p = Page[i]
        except Page.DoesNotExist:
            try:
                p = Page.create(
                    id=i,
                    url=pageinfo['url'],
                    title=pageinfo['title'],
                    is_redirect=pageinfo['is_redirect'],
                    touched=datetime.datetime.fromtimestamp(pageinfo["touched"]),
                    is_sync = True
                )
                update_page(p, pageinfo)
            except IntegrityError:
                print("\x1b[31mSkipping {i}: Integrity error\x1b[0m".format(i=i))
                failed += 1
                continue
        else:
            if pageinfo["touched"] > p.touched:
                update_page(p, pageinfo)
        passed += 1
    with open(DATABASE_DIR + "/last_sync", "w") as fw:
        fw.write(str(time.time()))
    if passed > 0 and failed == 0:
        print("\x1b[32mSuccessfully updated {p} pages :)\x1b[0m".format(p=passed))
    else:
        print("\x1b[33m{p} pages successfully updated, {f} errors.\x1b[0m".format(p=passed, f=failed))
    

if __name__ == "__main__":
    main()
