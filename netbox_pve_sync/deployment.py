"""Operator-only PostgreSQL bootstrap and migration commands.

Credentials are read from protected files and never accepted on the command line.
This module is included in the application image but is not imported by runtime
services.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .source_registry import SCHEMA_NAME_PATTERN


DATABASE_ROLES = {
    'owner': 'infra_sync_owner',
    'web_reader': 'infra_sync_web_reader',
    'registration_writer': 'infra_sync_registration_writer',
    'discovery_reader': 'infra_sync_discovery_reader',
    'apply_registry_reader': 'infra_sync_apply_registry_reader',
    'registry_reader': 'infra_sync_registry_reader',
    'run_writer': 'infra_sync_run_writer',
    'schedule_writer': 'infra_sync_schedule_writer',
}
PASSWORD_FILES = {
    'bootstrap': 'postgres_bootstrap_password',
    **{key: key + '_password' for key in DATABASE_ROLES},
}
SOURCE_COLUMNS = (
    'id', 'source_instance', 'name', 'source_type', 'address', 'enabled',
    'sync_enabled', 'sync_interval_seconds', 'verify_ssl', 'site_slug',
    'device_role_slug', 'platform_slug', 'device_type_slug', 'cluster_type_slug',
    'cluster_name', 'username', 'token_id_provider', 'token_id_key',
    'token_secret_provider', 'token_secret_key', 'legacy_identity_owner', 'settings',
    'created_at', 'updated_at',
)
PUBLIC_SOURCE_COLUMNS = (
    'source_instance', 'source_type', 'name', 'address', 'enabled',
    'sync_enabled', 'verify_ssl', 'sync_interval_seconds', 'site_slug',
    'cluster_name', 'platform_slug', 'device_role_slug', 'device_type_slug',
    'cluster_type_slug', 'legacy_identity_owner',
)
REGISTRATION_INSERT_COLUMNS = SOURCE_COLUMNS[:-2]
RUN_INSERT_COLUMNS = (
    'run_id', 'source_instance', 'source_type', 'trigger', 'started_at', 'status',
    'plan_digest', 'planner_version', 'created_by',
)
RUN_UPDATE_COLUMNS = (
    'finished_at', 'duration_ms', 'status', 'plan_digest', 'planner_version',
    'create_count', 'update_count', 'no_change_count', 'review_required_count',
    'blocked_count', 'ignored_count', 'unsupported_count', 'retain_only_count',
    'error_code', 'error_message_safe',
)


class DeploymentError(RuntimeError):
    """Safe operator-facing deployment failure."""


def _required_setting(name, environ=None):
    value = (environ or os.environ).get(name, '').strip()
    if not value:
        raise DeploymentError(f'{name} is required')
    return value


def read_password(key, environ=None):
    """Read one bounded single-line password from the dedicated directory."""
    environ = environ or os.environ
    root = Path(_required_setting('INFRA_SYNC_DB_PASSWORD_DIR', environ))
    filename = PASSWORD_FILES[key]
    path = root / filename
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise DeploymentError(f'invalid credential file: {filename}')
        value = path.read_text(encoding='utf-8').rstrip('\r\n')
    except OSError as exc:
        raise DeploymentError(f'credential file unavailable: {filename}') from exc
    if not value or '\n' in value or '\r' in value:
        raise DeploymentError(f'invalid credential file: {filename}')
    return value


def connection_info(role_key, environ=None):
    """Build libpq configuration without putting credentials in argv or logs."""
    environ = environ or os.environ
    role = ('infra_sync_bootstrap' if role_key == 'bootstrap'
            else DATABASE_ROLES[role_key])
    return make_conninfo(
        host=_required_setting('INFRA_SYNC_DB_HOST', environ),
        port=environ.get('INFRA_SYNC_DB_PORT', '5432'),
        dbname=environ.get('INFRA_SYNC_DB_NAME', 'infra_sync'),
        user=role,
        password=read_password(role_key, environ),
        connect_timeout='5',
    )


def _execute_role(cursor, role, password):
    cursor.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,))
    if cursor.fetchone() is None:
        cursor.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    # PostgreSQL utility statements don't accept bind parameters for PASSWORD.
    # psycopg.sql.Literal performs driver quoting; the composed query is never logged.
    cursor.execute(sql.SQL(
        'ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB '
        'NOCREATEROLE NOINHERIT NOREPLICATION'
    ).format(sql.Identifier(role), sql.Literal(password)))


def bootstrap_roles(environ=None):
    """Create/rotate fixed runtime roles and establish private DB ownership."""
    environ = environ or os.environ
    database = environ.get('INFRA_SYNC_DB_NAME', 'infra_sync')
    with psycopg.connect(connection_info('bootstrap', environ), autocommit=True) as connection:
        with connection.cursor() as cursor:
            for key, role in DATABASE_ROLES.items():
                _execute_role(cursor, role, read_password(key, environ))
                read_only = key in {
                    'web_reader', 'discovery_reader', 'apply_registry_reader',
                    'registry_reader',
                }
                cursor.execute(sql.SQL(
                    'ALTER ROLE {} SET default_transaction_read_only={}'
                ).format(sql.Identifier(role), sql.SQL('on' if read_only else 'off')))
            cursor.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(
                sql.Identifier(database), sql.Identifier(DATABASE_ROLES['owner'])))
            cursor.execute(sql.SQL('REVOKE CONNECT, TEMP ON DATABASE {} FROM PUBLIC').format(
                sql.Identifier(database)))
            for role in DATABASE_ROLES.values():
                cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                    sql.Identifier(database), sql.Identifier(role)))


def migrate(environ=None):
    """Run the reviewed Alembic chain as owner, using an injected connection."""
    environ = environ or os.environ
    schema = environ.get('INFRA_SYNC_REGISTRY_SCHEMA', 'infra_sync')
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise DeploymentError('INFRA_SYNC_REGISTRY_SCHEMA is invalid')
    engine = sa.create_engine(
        'postgresql+psycopg://',
        creator=lambda: psycopg.connect(connection_info('owner', environ)),
        poolclass=sa.pool.NullPool,
        hide_parameters=True,
    )
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    config.attributes['schema'] = schema
    try:
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
    finally:
        engine.dispose()


def _columns(names):
    return sql.SQL(', ').join(sql.Identifier(name) for name in names)


def _grant_columns(cursor, privilege, table, columns, role):
    cursor.execute(sql.SQL('GRANT {} ({}) ON {} TO {}').format(
        sql.SQL(privilege), _columns(columns), table, sql.Identifier(role)))


def apply_grants(environ=None):
    """Reapply the complete least-privilege matrix after every migration."""
    environ = environ or os.environ
    schema = environ.get('INFRA_SYNC_REGISTRY_SCHEMA', 'infra_sync')
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise DeploymentError('INFRA_SYNC_REGISTRY_SCHEMA is invalid')
    owner = DATABASE_ROLES['owner']
    sources = sql.Identifier(schema, 'sources')
    meta = sql.Identifier(schema, 'schema_meta')
    runs = sql.Identifier(schema, 'sync_runs')
    with psycopg.connect(connection_info('owner', environ)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(
                sql.Identifier(schema)))
            cursor.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(
                sql.Identifier(schema)))
            cursor.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM PUBLIC').format(
                sql.Identifier(schema)))
            cursor.execute(sql.SQL(
                'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} '
                'REVOKE ALL ON TABLES FROM PUBLIC'
            ).format(sql.Identifier(owner), sql.Identifier(schema)))
            cursor.execute(sql.SQL(
                'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} '
                'REVOKE ALL ON SEQUENCES FROM PUBLIC'
            ).format(sql.Identifier(owner), sql.Identifier(schema)))
            cursor.execute(sql.SQL(
                'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} '
                'REVOKE ALL ON FUNCTIONS FROM PUBLIC'
            ).format(sql.Identifier(owner), sql.Identifier(schema)))
            for role in (value for key, value in DATABASE_ROLES.items() if key != 'owner'):
                cursor.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}').format(
                    sql.Identifier(schema), sql.Identifier(role)))
                cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                    sql.Identifier(schema), sql.Identifier(role)))

            for key in ('web_reader', 'registration_writer', 'discovery_reader',
                        'apply_registry_reader', 'registry_reader'):
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    meta, sql.Identifier(DATABASE_ROLES[key])))
            _grant_columns(cursor, 'SELECT', sources, PUBLIC_SOURCE_COLUMNS,
                           DATABASE_ROLES['web_reader'])
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                runs, sql.Identifier(DATABASE_ROLES['web_reader'])))
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                sources, sql.Identifier(DATABASE_ROLES['registration_writer'])))
            _grant_columns(cursor, 'INSERT', sources, REGISTRATION_INSERT_COLUMNS,
                           DATABASE_ROLES['registration_writer'])
            for key in ('discovery_reader', 'apply_registry_reader', 'registry_reader'):
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    sources, sql.Identifier(DATABASE_ROLES[key])))
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                runs, sql.Identifier(DATABASE_ROLES['run_writer'])))
            _grant_columns(cursor, 'INSERT', runs, RUN_INSERT_COLUMNS,
                           DATABASE_ROLES['run_writer'])
            _grant_columns(cursor, 'UPDATE', runs, RUN_UPDATE_COLUMNS,
                           DATABASE_ROLES['run_writer'])
            _grant_columns(cursor, 'SELECT', sources,
                           ('source_instance', 'sync_enabled', 'sync_interval_seconds'),
                           DATABASE_ROLES['schedule_writer'])
            _grant_columns(cursor, 'UPDATE', sources,
                           ('sync_enabled', 'sync_interval_seconds'),
                           DATABASE_ROLES['schedule_writer'])


def main(argv=None):
    """Run one explicit provisioning operation with sanitized failures."""
    parser = argparse.ArgumentParser(description='Infra Sync deployment database tool')
    parser.add_argument('operation', choices=('bootstrap-roles', 'migrate', 'apply-grants'))
    args = parser.parse_args(argv)
    actions = {
        'bootstrap-roles': bootstrap_roles,
        'migrate': migrate,
        'apply-grants': apply_grants,
    }
    try:
        actions[args.operation]()
    except Exception:  # pylint: disable=broad-exception-caught
        print(f'{args.operation} failed; inspect protected database configuration', file=sys.stderr)
        return 1
    print(f'{args.operation} completed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
