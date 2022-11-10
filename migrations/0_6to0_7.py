from playhouse.migrate import migrate, SqliteMigrator, MySQLMigrator
from peewee import MySQLDatabase, SqliteDatabase
from app import database

if type(database) == MySQLDatabase:
    migrator = MySQLMigrator(database)
elif type(database) == SqliteDatabase:
    migrator = SqliteMigrator(database)
else:
    print("Unsupported database")
    exit()

with database.atomic():
    migrate(
        
    )

