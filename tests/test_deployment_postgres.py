"""Opt-in destructive tests for a dedicated disposable PostgreSQL cluster."""

import os
import secrets

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from netbox_pve_sync import deployment


TEST_DSN = os.environ.get('INFRA_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN', '')


def _environment(tmp_path):
    if not TEST_DSN:
        pytest.skip('INFRA_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN is not configured')
    parsed = conninfo_to_dict(TEST_DSN)
    if parsed.get('dbname') != 'infra_sync_deployment_test':
        pytest.fail('deployment integration requires database infra_sync_deployment_test')
    if parsed.get('user') != 'infra_sync_bootstrap':
        pytest.fail('deployment integration requires user infra_sync_bootstrap')
    secret_root = tmp_path / 'secrets'
    secret_root.mkdir()
    passwords = {'bootstrap': parsed.get('password', '')}
    passwords.update({key: secrets.token_urlsafe(24) for key in deployment.DATABASE_ROLES})
    for key, filename in deployment.PASSWORD_FILES.items():
        path = secret_root / filename
        path.write_text(passwords[key] + '\n', encoding='utf-8')
        path.chmod(0o600)
    return {
        'INFRA_SYNC_DB_HOST': parsed.get('host', '127.0.0.1'),
        'INFRA_SYNC_DB_PORT': parsed.get('port', '5432'),
        'INFRA_SYNC_DB_NAME': parsed['dbname'],
        'INFRA_SYNC_DB_PASSWORD_DIR': str(secret_root),
        'INFRA_SYNC_REGISTRY_SCHEMA': 'infra_sync',
    }


def test_clean_bootstrap_migrate_grants_and_idempotency(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env)
    deployment.validate_migration_ownership(env)
    deployment.migrate(env)
    deployment.apply_grants(env)
    deployment.bootstrap_roles(env)
    deployment.validate_migration_ownership(env)
    deployment.migrate(env)
    deployment.apply_grants(env)

    with psycopg.connect(deployment.connection_info('bootstrap', env)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM infra_sync.alembic_version")
            assert cursor.fetchone() == ('0002_sync_run_history',)
            cursor.execute("SELECT count(*) FROM infra_sync.sources")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                           (list(deployment.DATABASE_ROLES.values()),))
            assert {row[0] for row in cursor.fetchall()} == set(
                deployment.DATABASE_ROLES.values())
            cursor.execute("SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication "
                           "FROM pg_roles WHERE rolname = ANY(%s)",
                           (list(deployment.DATABASE_ROLES.values()),))
            assert all(row[1:] == (False, False, False, False) for row in cursor.fetchall())
            cursor.execute("SELECT pg_get_userbyid(datdba) FROM pg_database "
                           "WHERE datname='infra_sync_deployment_test'")
            assert cursor.fetchone() == (deployment.DATABASE_ROLES['owner'],)


def test_runtime_role_grants_are_column_limited(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env)
    deployment.migrate(env)
    deployment.apply_grants(env)
    checks = {
        'discovery_reader': ('SELECT', 'sources'),
        'apply_registry_reader': ('SELECT', 'sources'),
        'registry_reader': ('SELECT', 'sources'),
    }
    with psycopg.connect(deployment.connection_info('bootstrap', env)) as connection:
        with connection.cursor() as cursor:
            for key, (allowed, table) in checks.items():
                role = deployment.DATABASE_ROLES[key]
                cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                               (role, f'infra_sync.{table}', allowed))
                assert cursor.fetchone() == (True,)
                cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                               (role, f'infra_sync.{table}', 'DELETE'))
                assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'infra_sync.sync_runs', 'run_id', 'INSERT'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'infra_sync.sync_runs', 'DELETE'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['web_reader'],
                            'infra_sync.sources', 'source_instance', 'SELECT'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['web_reader'],
                            'infra_sync.sources', 'username', 'SELECT'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['registration_writer'],
                            'infra_sync.sources', 'id', 'INSERT'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['registration_writer'],
                            'infra_sync.sources', 'created_at', 'INSERT'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                           (deployment.DATABASE_ROLES['registration_writer'],
                            'infra_sync.sources', 'UPDATE'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['schedule_writer'],
                            'infra_sync.sources', 'sync_enabled', 'UPDATE'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['schedule_writer'],
                            'infra_sync.sources', 'name', 'UPDATE'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'infra_sync.sync_runs', 'status', 'UPDATE'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'infra_sync.sources', 'SELECT'))
            assert cursor.fetchone() == (False,)


def test_migration_ownership_preflight_rejects_foreign_schema_owner(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env)
    deployment.migrate(env)
    owner = deployment.DATABASE_ROLES['owner']
    foreign = deployment.DATABASE_ROLES['discovery_reader']
    with psycopg.connect(deployment.connection_info('bootstrap', env), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('ALTER SCHEMA infra_sync OWNER TO {}').format(
                sql.Identifier(foreign)))
    try:
        with pytest.raises(deployment.DeploymentError, match='schema owner'):
            deployment.validate_migration_ownership(env)
    finally:
        with psycopg.connect(
                deployment.connection_info('bootstrap', env), autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('ALTER SCHEMA infra_sync OWNER TO {}').format(
                    sql.Identifier(owner)))
