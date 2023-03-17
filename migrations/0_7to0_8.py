from playhouse.migrate import migrate, SqliteMigrator, MySQLMigrator
from peewee import MySQLDatabase, SqliteDatabase, \
    IntegerField, DateTimeField, ForeignKeyField, DeferredForeignKey, BitField
from app import database, UserGroup, UserGroupMembership, PagePermission


if type(database) == MySQLDatabase:
    migrator = MySQLMigrator(database)
elif type(database) == SqliteDatabase:
    migrator = SqliteMigrator(database)
else:
    print("Unsupported database")
    exit()

with database.atomic():
    database.create_tables([UserGroup, UserGroupMembership, PagePermission])
    migrate(
        migrator.add_column('user', 'restrictions', BitField())
    )
    UserGroup.create(
        name='default',
        permissions=31
    )