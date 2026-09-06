"""Opt-in destructive logical backup/restore test for a disposable PostgreSQL DB."""

import os
import secrets
import shutil
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from deploy import backup
from netbox_pve_sync import deployment


TEST_DSN = os.environ.get('INFRA_SYNC_BACKUP_TEST_POSTGRES_DSN', '')


def _environment(tmp_path):
    if not TEST_DSN:
        pytest.skip('INFRA_SYNC_BACKUP_TEST_POSTGRES_DSN is not configured')
    parsed = conninfo_to_dict(TEST_DSN)
    if parsed.get('dbname') != 'infra_sync_backup_test':
        pytest.fail('backup integration requires database infra_sync_backup_test')
    if parsed.get('user') != 'infra_sync_bootstrap':
        pytest.fail('backup integration requires user infra_sync_bootstrap')
    if any(shutil.which(name) is None for name in ('pg_dump', 'pg_restore', 'psql')):
        pytest.skip('compatible PostgreSQL client tools are unavailable')
    root = tmp_path / 'passwords'
    root.mkdir()
    passwords = {'bootstrap': parsed.get('password', '')}
    passwords.update({key: secrets.token_urlsafe(24) for key in deployment.DATABASE_ROLES})
    for key, filename in deployment.PASSWORD_FILES.items():
        path = root / filename
        path.write_text(passwords[key] + '\n', encoding='utf-8')
        path.chmod(0o600)
    return {
        'INFRA_SYNC_DB_HOST': parsed.get('host', '127.0.0.1'),
        'INFRA_SYNC_DB_PORT': parsed.get('port', '5432'),
        'INFRA_SYNC_DB_NAME': parsed['dbname'],
        'INFRA_SYNC_DB_PASSWORD_DIR': str(root),
        'INFRA_SYNC_REGISTRY_SCHEMA': 'infra_sync',
    }


def _seed(connection):
    source_sql = """
        INSERT INTO infra_sync.sources (
          id, source_instance, name, source_type, address, enabled, sync_enabled,
          sync_interval_seconds, verify_ssl, site_slug, device_role_slug,
          platform_slug, device_type_slug, cluster_type_slug, cluster_name,
          username, token_id_provider, token_id_key, token_secret_provider,
          token_secret_key, legacy_identity_owner, settings
        ) VALUES (
          %s, %s, %s, %s, %s, true, %s, %s, false, 'test-site', 'server',
          %s, 'generic', 'virtualization', %s, %s, 'file', %s, 'file', %s, %s, %s
        )
    """
    with connection.cursor() as cursor:
        cursor.execute(source_sql, (
            'pve-row', 'pve-backup-test', 'PVE backup test', 'proxmox', 'pve.invalid',
            True, 300, 'proxmox', 'PVE', 'root@pam', 'pve-token-id',
            'pve-token-secret', True, Jsonb({'unknown_future_key': 'preserved'})))
        cursor.execute(source_sql, (
            'esxi-row', 'esxi-backup-test', 'ESXi backup test', 'esxi', 'esxi.invalid',
            False, 600, 'vmware', 'ESXi', 'readonly', 'esxi-user',
            'esxi-password', False, Jsonb({'another_unknown_key': 7})))
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cursor.execute(
            "INSERT INTO infra_sync.sync_runs "
            "(run_id, source_instance, source_type, trigger, started_at, status, created_by) "
            "VALUES (%s, 'pve-backup-test', 'proxmox', 'scheduled', %s, "
            "'RUNNING', 'scheduler')", (uuid.uuid4(), started))
        cursor.execute(
            "INSERT INTO infra_sync.sync_runs "
            "(run_id, source_instance, source_type, trigger, started_at, finished_at, "
            "duration_ms, status, created_by) VALUES "
            "(%s, 'esxi-backup-test', 'esxi', 'manual', %s, %s, 1000, "
            "'SUCCEEDED', 'operator')", (uuid.uuid4(), started, started))


def _snapshot(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT * FROM infra_sync.sources ORDER BY source_instance')
        sources = cursor.fetchall()
        cursor.execute('SELECT * FROM infra_sync.sync_runs ORDER BY source_instance, run_id')
        runs = cursor.fetchall()
        cursor.execute('SELECT version_num FROM infra_sync.alembic_version')
        revision = cursor.fetchone()[0]
    return sources, runs, revision


def test_custom_dump_round_trip_preserves_multi_source_and_history(tmp_path):
    """Includes distinct providers, intervals, refs, settings, and stale RUNNING."""
    environment = _environment(tmp_path)
    deployment.bootstrap_roles(environment)
    with psycopg.connect(deployment.connection_info('bootstrap', environment),
                         autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA IF EXISTS infra_sync CASCADE')
    deployment.migrate(environment)
    deployment.apply_grants(environment)
    with psycopg.connect(deployment.connection_info('bootstrap', environment)) as connection:
        _seed(connection)
        connection.commit()
        expected = _snapshot(connection)

    tool = backup.DatabaseTool(
        tmp_path, 'external', {'INFRA_SYNC_BACKUP_DSN': TEST_DSN})
    dump = tmp_path / 'database.dump'
    tool.dump(dump)
    tool.verify_dump(dump)
    assert tool.metadata()['source_count'] == 2
    assert tool.metadata()['run_count'] == 2

    with psycopg.connect(deployment.connection_info('bootstrap', environment),
                         autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA infra_sync CASCADE')
    deployment.migrate(environment)
    assert tool.target_counts() == (0, 0)
    tool.restore(dump)
    deployment.migrate(environment)
    deployment.apply_grants(environment)
    with psycopg.connect(deployment.connection_info('bootstrap', environment)) as connection:
        assert _snapshot(connection) == expected
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='infra_sync' AND relname='sources'")
            assert cursor.fetchone() == ('infra_sync_owner',)
            cursor.execute("SELECT has_table_privilege('infra_sync_web_reader', "
                           "'infra_sync.sync_runs', 'SELECT')")
            assert cursor.fetchone() == (True,)
