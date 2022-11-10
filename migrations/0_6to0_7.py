from playhouse.migrate import migrate, SqliteMigrator, MySQLMigrator
from peewee import MySQLDatabase, SqliteDatabase, \
    IntegerField, DateTimeField, ForeignKeyField
from app import database, User

if type(database) == MySQLDatabase:
    migrator = MySQLMigrator(database)
elif type(database) == SqliteDatabase:
    migrator = SqliteMigrator(database)
else:
    print("Unsupported database")
    exit()

with database.atomic():
    database.create_tables([User])
    migrate(
        migrator.add_column('page', 'calendar', DateTimeField(index=True, null=True)),
        migrator.add_column('page', 'owner_id', IntegerField(null=True))
    )

