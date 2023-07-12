# What’s New

## 0.8

+ Schema changes:
  + New tables `UserGroup`, `UserGroupMembership` and `PagePermission`.
  + Added flag `is_cw` to `Page`.
  + Added `restrictions` field to `User`.
+ Pages now can have a Content Warning. It prevents them to show up in previews, and adds a
  caution message when viewing them.
+ SEO improvement: added `keywords` and `description` meta tags to viewing pages.
+ Added Terms, Privacy Policy and Rules.
+ Changed user page URLs (contributions page) from `/u/user` to `/@user`.
+ `/manage/` is now a list of all managing options, including export/import and the brand new 
  `/manage/accounts`.
+ Users can now be disabled (and re-enabled) by administrator.
+ TOC is now shown in pages when screen width is greater than 960 pixels.
+ Style changes: added a top bar with the site title. It replaces the floating menu on the top right.
+ Now logged-in users have an “Edit” button below the first heading. All users can access page history
  by clicking the last modified time.
+ Added a built-in installer (`app_init.py`). You still need to manually create `site.conf`.

## 0.7.1

+ Improved calendar view. Now `/calendar` shows a list of years and months.

## 0.7

+ Schema changes:
  + Removed `PagePolicy` and `PagePolicyKey` tables altogether. They were never useful.
  + Added `calendar` field to `Page`.
  + Added `User` table.
+ Added `Flask-Login` and `Flask-WTF` dependencies in order to implement user logins.
+ Added `python-i18n` as a dependency.  Therefore, i18n changed format, using JSON files now.
+ Login is now required for creating and editing.
+ Now you can leave a comment while changing a page’s text. Moreover, a new revision is created now
  only in case of an effective text change.
+ Now a page can be dated in the calendar.
+ Now you can export and import pages in a JSON format. Importing can be done by admin users only.
+ Improved page history view, and added user contributions page.
+ Updated Markdown extensions to work under latest version.
+ Like it or not, now gzip library is required.
+ Added CSS variables in the site style.
+ Templates are now with `.jinja2` extension.

## 0.6

+ Added support for database URLs: you can now specify the URL of the database
  in `site.conf` by setting `[database]url`, be it MySQL, PostgreSQL or SQLite.
+ Added experimental math support, with `markdown_katex` library. The math
  parsing can be opted out in many ways.
+ Backlinks can now be accessed for each page.
+ Spoiler tags at beginning of line now work. Just for now.
+ Removed `Upload` table.
+ Added `PageLink` table.

## 0.5

+ Removed support for uploads. The `/upload/` endpoint now points to an info
  page, and the “Upload image” button and gallery from home page are now gone.
+ `markdown_strikethrough` extension is no more needed. Now there are two new
  built-in extensions: `StrikethroughExtension` and `SpoilerExtension` (the
  last one is buggy tho).
+ Removed support for magic words (the commands between `{{` `}}`). These
  features are now lost: `backto`, `media` and `gallery` (easily replaceable
  with simple Markdown).
+ Added app version to site footer.
+ Added client-side drafts (they require JS enabled).

## 0.4



## 0.3



## 0.2

+ Some code refactoring.
+ Light and dark theme.
+ Move database into `database/` folder.
+ Style improvements.
