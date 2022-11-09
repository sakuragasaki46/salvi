# Salvi

Salvi is a simple wiki-like note-taking web application, written in Python using
Flask framework.

**Warning**: Salvi is designed for personal, individual use.  It may not be
suitable as a community or team knowledge base.

## Features

+ Write notes on the go, using Markdown syntax
+ Any note can have its own URL
+ Revision history
+ Stored in SQLite/MySQL databases
+ Material Icons
+ Light/dark theme
+ Works fine even with JavaScript disabled.

## Requirements

+ **Python** 3.6+.
+ **Flask** web framework (and Flask-Login / Flask-WTF extensions).
+ **Peewee** ORM.
+ **Markdown** for page rendering.
+ **Python-I18n**.

### Optional requirements

* **Markdown-KaTeX** if you want to display math inside pages.

## Caveats

+ All pages created are, as of now, viewable and editable by anyone, with no
  trace of users and/or passwords.

## License

[MIT License](./LICENSE).
