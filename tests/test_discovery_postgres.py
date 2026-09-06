"""Disposable PostgreSQL proof for the WEB-4 SELECT-only worker role."""

import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from netbox_sync.discovery_worker import DiscoverySupervisor
from netbox_sync.source_registry import SourceRegistry
from tests.sample_data import sample_source_config
from tests.test_source_registry_postgres import _safe_test_dsn


def test_discovery_reader_exact_grants_allow_lookup_and_deny_mutation():
    """Exercise the production repository with only documented WEB-4 grants."""
    admin_dsn = _safe_test_dsn()
    suffix = uuid.uuid4().hex
    schema = f'netbox_sync_test_{suffix}'
    role = f'netbox_sync_discovery_{suffix}'
    password = f'fake-{suffix}'
    registry = SourceRegistry(lambda: psycopg.connect(admin_dsn), schema)
    registry.initialize()
    registry.create_source(sample_source_config())
    with psycopg.connect(admin_dsn) as connection:
        database = connection.info.dbname
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(role), sql.Literal(password)))
            cursor.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(
                sql.Identifier(database), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                sql.Identifier(database), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT SELECT (key, value) ON {} TO {}').format(
                sql.Identifier(schema, 'schema_meta'), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                sql.Identifier(schema, 'sources'), sql.Identifier(role)))
    reader_dsn = make_conninfo(admin_dsn, user=role, password=password)
    supervisor = DiscoverySupervisor(reader_dsn, schema, '/missing', '/missing',
                                     'http://netbox.invalid', '/missing', 10001, 10001)
    assert supervisor._source('pve-infra-test').source_instance == 'pve-infra-test'  # pylint: disable=protected-access
    forbidden = ('INSERT INTO {}.schema_meta VALUES (\'x\', \'x\')',
                 'UPDATE {}.sources SET enabled = FALSE', 'DELETE FROM {}.sources',
                 'TRUNCATE {}.sources', 'CREATE TABLE {}.forbidden (id integer)')
    for statement in forbidden:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), psycopg.connect(reader_dsn) as connection:
            connection.execute(sql.SQL(statement).format(sql.Identifier(schema)))
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        connection.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM {}').format(
            sql.Identifier(connection.info.dbname), sql.Identifier(role)))
        connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
