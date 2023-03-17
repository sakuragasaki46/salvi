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
+ Calendar
+ Works fine even with JavaScript disabled.

## Requirements

+ **Python** 3.6+.
+ **Flask** web framework (and Flask-Login / Flask-WTF extensions).
+ **Peewee** ORM.
+ **Markdown** for page rendering.
+ **Python-I18n**.
+ The database drivers needed for the type of database.

### Optional requirements

* **Markdown-KaTeX** if you want to display math inside pages.

## Usage

+ Clone this repository: `git clone https://github.com/sakuragasaki46/salvi`
+ Edit site.conf with the needed parameters. An example site.conf:

```
[site]
name = Salvi

[database]
directory = /path/to/database/
```

+ Run `python3 -m app_init` to initialize the database and create the administrator user.
+ Run `flask run`.
+ You can now access Salvi in your browser at port 5000.

## Caveats

+ The whole application is untested.
+ If you forget the password, there is currently no way to reset it.

## License

[MIT License](./LICENSE).
