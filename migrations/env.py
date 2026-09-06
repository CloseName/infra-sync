"""Explicit, transactional PostgreSQL migrations; never imported by sync."""

# Alembic installs these context proxy members dynamically while loading env.py.
# pylint: disable=no-member

import os
import re

import psycopg
import sqlalchemy as sa
from alembic import context


def run(connection, schema):
    """Serialize migration writers and scope all Alembic state to the registry."""
    if connection.dialect.name != 'postgresql':
        raise ValueError('PostgreSQL is required')
    if not isinstance(schema, str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,62}', schema):
        raise ValueError('A safe explicit registry schema is required')
    with connection.begin():
        connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(
            sa.text('SELECT pg_advisory_xact_lock(hashtext(:key))'),
            {'key': 'netbox-sync-migrations:' + schema},
        )
        connection.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
        context.configure(
            connection=connection,
            version_table_schema=schema,
            transaction_per_migration=False,
        )
        with context.begin_transaction():
            context.run_migrations(schema=schema)


def main():
    """Use injected test connection or the same libpq DSN format as runtime."""
    if context.is_offline_mode():
        raise ValueError('Offline migrations are unsupported: legacy validation requires PostgreSQL')
    config = context.config
    schema = config.attributes.get('schema') or os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA')
    supplied = config.attributes.get('connection')
    if supplied is not None:
        run(supplied, schema)
        return
    dsn = os.environ.get('NETBOX_SYNC_REGISTRY_DSN')
    if not dsn:
        raise ValueError('NETBOX_SYNC_REGISTRY_DSN is required')
    engine = sa.create_engine(
        'postgresql+psycopg://',
        creator=lambda: psycopg.connect(dsn),
        poolclass=sa.pool.NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            run(connection, schema)
    except Exception:
        # DB driver errors can embed credentials/DSNs. Never echo raw exceptions.
        raise RuntimeError('Registry migration failed; verify configuration and schema compatibility') from None
    finally:
        engine.dispose()


main()
