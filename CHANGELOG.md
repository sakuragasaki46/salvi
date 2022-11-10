# What’s New

## 0.7

+ Schema changes:
  + Removed `PagePolicy` and `PagePolicyKey` tables altogether. They were never useful.
  + Added `calendar` field to `Page`.
  + Added `User` table.
+ Added `Flask-Login` and `Flask-WTF` dependencies in order to implement user logins.
+ Added `python-i18n` as a dependency.  Therefore, i18n changed format, using JSON files now.
+ Like it or not, now gzip library is required.

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
