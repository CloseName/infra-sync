"""Opt-in database naming transition against a marked disposable PostgreSQL cluster."""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from netbox_sync import deployment


TEST_DSN = os.environ.get('NETBOX_SYNC_NAMING_TEST_POSTGRES_DSN', '')


def _marked_test_dsn():
    if not TEST_DSN:
        pytest.skip('NETBOX_SYNC_NAMING_TEST_POSTGRES_DSN is not configured')
    parsed = conninfo_to_dict(TEST_DSN)
    if (parsed.get('dbname'), parsed.get('user')) != (
            deployment.LEGACY_DATABASE_NAME, deployment.LEGACY_BOOTSTRAP_ROLE):
        pytest.fail('naming migration test requires the exact legacy test identity')
    if parsed.get('host') not in {'127.0.0.1', 'localhost'}:
        pytest.fail('naming migration test requires a loopback PostgreSQL host')
    with psycopg.connect(TEST_DSN) as connection:
        marker = connection.execute(
            'SELECT current_setting(%s, true)', ('netbox_sync.disposable_test',)).fetchone()[0]
    if marker != 'on':
        pytest.fail('PostgreSQL cluster is not marked as disposable')
    return parsed


def _password_environment(tmp_path, parsed):
    root = Path(tmp_path) / 'passwords'
    root.mkdir()
    for key, filename in deployment.PASSWORD_FILES.items():
        value = parsed.get('password', '') if key == 'bootstrap' else 'fake-' + key
        (root / filename).write_text(value + '\n', encoding='utf-8')
    return {
        'NETBOX_SYNC_DB_HOST': parsed.get('host', '127.0.0.1'),
        'NETBOX_SYNC_DB_PORT': parsed.get('port', '5432'),
        'NETBOX_SYNC_DB_NAME': deployment.DATABASE_NAME,
        'NETBOX_SYNC_DB_PASSWORD_DIR': str(root),
        'NETBOX_SYNC_NAMING_CONFIRM': deployment.NAMING_CONFIRMATION,
    }


def test_database_schema_roles_and_rows_transition_without_drops(tmp_path):
    parsed = _marked_test_dsn()
    with psycopg.connect(TEST_DSN, autocommit=True) as connection:
        cursor = connection.cursor()
        for role in deployment.LEGACY_DATABASE_ROLES.values():
            cursor.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
        cursor.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}').format(
            sql.Identifier(deployment.LEGACY_SCHEMA_NAME),
            sql.Identifier(deployment.LEGACY_DATABASE_ROLES['owner'])))
        cursor.execute('CREATE TABLE infra_sync.alembic_version(version_num text primary key)')
        cursor.execute("INSERT INTO infra_sync.alembic_version VALUES ('0002_sync_run_history')")
        cursor.execute('CREATE TABLE infra_sync.schema_meta(key text primary key, value text)')
        cursor.execute("INSERT INTO infra_sync.schema_meta VALUES ('schema_version', '1')")
        cursor.execute('CREATE TABLE infra_sync.sources(id text primary key)')
        cursor.execute("INSERT INTO infra_sync.sources VALUES ('source-preserved')")
        cursor.execute('CREATE TABLE infra_sync.sync_runs(id text primary key)')
        cursor.execute("INSERT INTO infra_sync.sync_runs VALUES ('run-preserved')")

    deployment.migrate_database_naming(_password_environment(tmp_path, parsed))

    target = psycopg.conninfo.make_conninfo(
        TEST_DSN, dbname=deployment.DATABASE_NAME, user=deployment.BOOTSTRAP_ROLE)
    with psycopg.connect(target) as connection:
        assert connection.execute('SELECT id FROM netbox_sync.sources').fetchone() == (
            'source-preserved',)
        assert connection.execute('SELECT id FROM netbox_sync.sync_runs').fetchone() == (
            'run-preserved',)
        assert connection.execute(
            'SELECT version_num FROM netbox_sync.alembic_version').fetchone() == (
                '0002_sync_run_history',)
        owners = connection.execute(
            "SELECT DISTINCT pg_get_userbyid(c.relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='netbox_sync' AND c.relkind='r'").fetchall()
        assert owners == [(deployment.DATABASE_ROLES['owner'],)]
        existing = {row[0] for row in connection.execute(
            'SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)',
            ([deployment.LEGACY_BOOTSTRAP_ROLE,
              *deployment.LEGACY_DATABASE_ROLES.values(), deployment.BOOTSTRAP_ROLE,
              *deployment.DATABASE_ROLES.values()],)).fetchall()}
    assert existing == {
        deployment.LEGACY_BOOTSTRAP_ROLE, *deployment.LEGACY_DATABASE_ROLES.values(),
        deployment.BOOTSTRAP_ROLE, *deployment.DATABASE_ROLES.values()}
