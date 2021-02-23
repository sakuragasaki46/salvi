from flask import Blueprint, render_template, request
import json, datetime

from app import Page, PageTag

bp = Blueprint('importexport', __name__)

class Exporter(object):
    def __init__(self):
        self.root = {'pages': [], 'users': {}}
    def add_page(self, p, include_history=True, include_users=False):
        pobj = {}
        pobj['title'] = p.title
        pobj['url'] = p.url
        pobj['tags'] = [tag.name for tag in p.tags]
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

@bp.route('/manage/export/', methods=['GET', 'POST'])
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
            return render_template('exportpages.html')
        query = q_list.pop(0)
        while q_list:
            query |= q_list.pop(0)
        e = Exporter()
        e.add_page_list(query)
        return e.export(), {'Content-Type': 'application/json', 'Content-Disposition': 'attachment; ' + 
            'filename=export-{}.json'.format(datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))}
    return render_template('exportpages.html')

@bp.route('/manage/import/', methods=['GET', 'POST'])
def importpages():
    return render_template('importpages.html')

