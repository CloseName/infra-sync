"""PostgreSQL integration tests for the Source Registry foundation."""

import os
import uuid
from dataclasses import replace

import psycopg
import pytest
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict

from netbox_pve_sync.source_config import SecretReference, SourceCredentials
from netbox_pve_sync.source_bootstrap import bootstrap_legacy_source
from netbox_pve_sync.source_registry import (
    SourceConflictError,
    SourceRecord,
    SourceRegistry,
)

from tests.sample_data import sample_source_config


TEST_DSN_VARIABLE = 'INFRA_SYNC_TEST_POSTGRES_DSN'
TEST_DATABASE_NAME = 'infra_sync_test'
TEST_SCHEMA_PREFIX = 'infra_sync_test_'
FAKE_SECRET = 'FAKE_SECRET_VALUE_DO_NOT_STORE'


def _config(**changes):
    return replace(sample_source_config(), **changes)


def _esxi_config(source_id='esxi-a', **changes):
    password = SecretReference(provider='env', key='ESXI_A_PASSWORD')
    values = {
        'id': source_id,
        'source_instance': source_id,
        'source_type': 'esxi',
        'legacy_identity_owner': False,
        'credentials': SourceCredentials.for_password('root', password),
    }
    values.update(changes)
    return _config(**values)


def _safe_test_dsn():
    dsn = os.environ.get(TEST_DSN_VARIABLE, '').strip()
    if not dsn:
        pytest.skip(f'{TEST_DSN_VARIABLE} is not configured')

    database = conninfo_to_dict(dsn).get('dbname')
    if database != TEST_DATABASE_NAME:
        pytest.fail(
            f'{TEST_DSN_VARIABLE} must target database {TEST_DATABASE_NAME!r}'
        )
    return dsn


def _registry_without_database():
    def reject_connection():
        raise AssertionError('validation must happen before database access')

    return SourceRegistry(reject_connection, 'infra_sync_test_validation')


def test_domain_validation_happens_before_database_access():
    registry = _registry_without_database()

    with pytest.raises(ValueError, match='source_instance'):
        _config(source_instance='INVALID INSTANCE')
    with pytest.raises(ValueError, match='positive integer'):
        _config(sync_interval_seconds=0)
    with pytest.raises(ValueError, match='settings must be a mapping'):
        _config(settings=['not', 'an', 'object'])
    with pytest.raises(ValueError, match='unsupported source_type'):
        registry.create_source(_config(source_type='xen'))


def test_invalid_secret_reference_is_rejected_before_database_access():
    registry = _registry_without_database()
    config = _config()
    invalid_provider = replace(
        config.credentials,
        token_secret=SecretReference(provider='vault', key='future-key'),
    )
    plaintext = replace(
        config.credentials,
        token_secret='FAKE_SECRET_VALUE_DO_NOT_STORE',
    )

    with pytest.raises(ValueError, match='unsupported secret provider'):
        registry.create_source(replace(config, credentials=invalid_provider))
    with pytest.raises(TypeError, match='SecretReference'):
        registry.create_source(replace(config, credentials=plaintext))


def test_esxi_legacy_identity_owner_is_rejected_before_database_access():
    registry = _registry_without_database()

    with pytest.raises(ValueError, match='legacy identity owner'):
        registry.create_source(
            _config(source_type='esxi', legacy_identity_owner=True)
        )


@pytest.fixture
def pg_registry():
    dsn = _safe_test_dsn()
    schema = TEST_SCHEMA_PREFIX + uuid.uuid4().hex

    def connect():
        return psycopg.connect(dsn)

    registry = SourceRegistry(connect, schema)
    registry.initialize()
    try:
        yield registry, connect
    finally:
        assert schema.startswith(TEST_SCHEMA_PREFIX)
        with connect() as connection:
            connection.execute(
                sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema))
            )


def test_initialize_empty_database_is_idempotent(pg_registry):
    registry, _ = pg_registry

    assert registry.schema_version() == 1
    assert registry.list_sources() == ()
    registry.initialize()
    assert registry.schema_version() == 1
    assert registry.list_sources() == ()


def test_create_get_list_and_source_config_conversion(pg_registry):
    registry, _ = pg_registry
    config = _config(settings={'pool': 'infra', 'limits': {'batch': 10}})

    created = registry.create_source(config)

    assert isinstance(created, SourceRecord)
    assert created.id == config.id
    assert created.source_instance == config.source_instance
    assert created.created_at.tzinfo is not None
    assert created.updated_at == created.created_at
    assert registry.get_source(config.id) == created
    assert registry.get_by_source_instance(config.source_instance) == created
    assert registry.list_sources() == (created,)
    assert registry.get_source_config(config.id) == config
    assert dict(created.config.settings) == {
        'limits': {'batch': 10},
        'pool': 'infra',
    }


def test_isolated_list_contains_malformed_row_without_blocking_valid_row(pg_registry):
    registry, connect = pg_registry
    registry.create_source(_config(id='a-invalid', source_instance='a-invalid'))
    registry.create_source(_config(id='b-valid', source_instance='b-valid',
                                   legacy_identity_owner=False))
    with connect() as connection:
        connection.execute(sql.SQL(
            "UPDATE {} SET token_id_provider='unsupported' WHERE id='a-invalid'"
        ).format(sql.Identifier(registry.schema, 'sources')))
    with pytest.raises(ValueError, match='unsupported secret provider'):
        registry.list_sources()
    results = registry.list_sources_isolated()
    assert tuple(result.valid for result in results) == (False, True)
    assert results[0].record is None
    assert results[1].record.source_instance == 'b-valid'


def test_duplicate_id_and_source_instance_fail_without_partial_rows(pg_registry):
    registry, _ = pg_registry
    config = _config()
    registry.create_source(config)

    with pytest.raises(SourceConflictError, match='duplicate'):
        registry.create_source(replace(config, source_instance='pve-other'))
    with pytest.raises(SourceConflictError, match='duplicate'):
        registry.create_source(replace(config, id='other-source'))

    assert registry.list_sources() == (registry.get_source(config.id),)


@pytest.mark.parametrize('provider', ('env', 'file'))
def test_secret_references_round_trip_without_resolution(pg_registry, provider):
    registry, _ = pg_registry
    credentials = SourceCredentials(
        username='sync@pve',
        token_id=SecretReference(provider=provider, key='PVE_TOKEN_ID'),
        token_secret=SecretReference(provider=provider, key='PVE_TOKEN_SECRET'),
    )

    stored = registry.create_source(_config(credentials=credentials))

    assert stored.config.credentials == credentials


def test_settings_database_constraint_rejects_non_object(pg_registry):
    registry, connect = pg_registry
    created = registry.create_source(_config())

    with pytest.raises(errors.CheckViolation):
        with connect() as connection:
            connection.execute(
                sql.SQL('UPDATE {} SET settings = %s WHERE id = %s').format(
                    sql.Identifier(registry.schema, 'sources')
                ),
                (psycopg.types.json.Jsonb([]), created.id),
            )

    assert dict(registry.get_source_config(created.id).settings) == {}


def test_mutable_update_and_noop_timestamp_behavior(pg_registry):
    registry, _ = pg_registry
    created = registry.create_source(_config())

    updated = registry.update_source(
        created.id,
        name='Renamed Proxmox',
        address='new-pve.example',
        sync_interval_seconds=900,
        settings={'pool': 'production'},
    )

    assert updated.config.name == 'Renamed Proxmox'
    assert updated.config.address == 'new-pve.example'
    assert updated.config.sync_interval_seconds == 900
    assert dict(updated.config.settings) == {'pool': 'production'}
    assert updated.created_at == created.created_at
    assert updated.updated_at > created.updated_at

    no_op = registry.update_source(created.id, name='Renamed Proxmox')
    assert no_op.updated_at == updated.updated_at


@pytest.mark.parametrize('field_name', ('id', 'source_instance', 'source_type'))
def test_identity_fields_are_immutable(pg_registry, field_name):
    registry, _ = pg_registry
    config = _config()
    registry.create_source(config)

    with pytest.raises(ValueError, match='immutable'):
        registry.update_source(config.id, **{field_name: 'changed'})

    assert registry.get_source_config(config.id) == config


def test_invalid_update_rolls_back(pg_registry):
    registry, _ = pg_registry
    config = _config()
    before = registry.create_source(config)

    with pytest.raises(ValueError, match='positive integer'):
        registry.update_source(
            config.id,
            name='must not persist',
            sync_interval_seconds=0,
        )

    assert registry.get_source(config.id) == before


def test_registry_has_no_delete_api(pg_registry):
    registry, _ = pg_registry
    assert not hasattr(registry, 'delete_source')


def test_plaintext_secret_settings_are_rejected_before_database_access():
    registry = _registry_without_database()

    with pytest.raises(ValueError, match='secret values'):
        registry.create_source(
            _config(settings={'token_secret_value': FAKE_SECRET})
        )


def test_registry_never_resolves_or_persists_secret_values(
        pg_registry,
        monkeypatch,
):
    registry, connect = pg_registry
    monkeypatch.setenv('PVE_REGISTRY_SECRET', FAKE_SECRET)
    credentials = SourceCredentials(
        username='sync@pve',
        token_id=SecretReference(provider='env', key='PVE_REGISTRY_TOKEN_ID'),
        token_secret=SecretReference(provider='file', key='pve-token-secret'),
    )

    created = registry.create_source(_config(credentials=credentials))

    with connect() as connection:
        row_text = connection.execute(
            sql.SQL(
                'SELECT row_to_json(source_row)::text AS value '
                'FROM {} AS source_row WHERE id = %s'
            ).format(sql.Identifier(registry.schema, 'sources')),
            (created.id,),
        ).fetchone()[0]

    assert FAKE_SECRET not in row_text
    stored = registry.get_source_config(created.id).credentials
    assert stored.token_id.key == 'PVE_REGISTRY_TOKEN_ID'
    assert stored.token_secret.key == 'pve-token-secret'


def test_guarded_bootstrap_create_update_and_noop_against_postgres(pg_registry):
    registry, _ = pg_registry
    initial = _config(address='old-pve.example')

    dry_create = bootstrap_legacy_source(registry, initial)
    assert dry_create.created == 1
    assert registry.list_sources() == ()

    bootstrap_legacy_source(registry, initial, confirmed=True)
    assert bootstrap_legacy_source(registry, initial).noop == 1

    desired = replace(initial, address='new-pve.example')
    dry_update = bootstrap_legacy_source(registry, desired)
    assert dry_update.updated == 1
    assert registry.get_source_config(initial.id).address == 'old-pve.example'

    bootstrap_legacy_source(registry, desired, confirmed=True)
    assert registry.get_source_config(initial.id).address == 'new-pve.example'
    assert bootstrap_legacy_source(registry, desired, confirmed=True).noop == 1


def test_runnable_source_listing_is_filtered_ordered_and_secret_opaque(
        pg_registry,
        monkeypatch,
):
    registry, _ = pg_registry
    monkeypatch.delenv('MISSING_MULTI_SOURCE_TOKEN', raising=False)
    credentials = SourceCredentials(
        username='sync@pve',
        token_id=SecretReference(provider='env', key='MISSING_MULTI_SOURCE_TOKEN'),
        token_secret=SecretReference(provider='file', key='missing-secret-file'),
    )
    configs = (
        _config(
            id='pve-b',
            source_instance='pve-b',
            credentials=credentials,
        ),
        _config(
            id='pve-a',
            source_instance='pve-a',
            credentials=credentials,
        ),
        _config(
            id='pve-disabled',
            source_instance='pve-disabled',
            enabled=False,
            credentials=credentials,
        ),
        _config(
            id='pve-sync-disabled',
            source_instance='pve-sync-disabled',
            sync_enabled=False,
            credentials=credentials,
        ),
    )
    for config in configs:
        registry.create_source(config)

    runnable = registry.list_runnable_sources()

    assert [config.id for config in runnable] == ['pve-a', 'pve-b']
    assert all(config.enabled and config.sync_enabled for config in runnable)
    assert all(config.credentials == credentials for config in runnable)


def test_esxi_source_round_trips_without_plaintext_password(
        pg_registry,
        monkeypatch,
):
    registry, connect = pg_registry
    plaintext = 'FAKE_ESXI_PASSWORD_DO_NOT_STORE'
    monkeypatch.setenv('ESXI_A_PASSWORD', plaintext)

    created = registry.create_source(_esxi_config())

    assert created.config.source_type == 'esxi'
    assert created.config.credentials.username == 'root'
    assert created.config.credentials.password_reference == SecretReference(
        provider='env', key='ESXI_A_PASSWORD'
    )
    with connect() as connection:
        row_text = connection.execute(
            sql.SQL(
                'SELECT row_to_json(source_row)::text '
                'FROM {} AS source_row WHERE id = %s'
            ).format(sql.Identifier(registry.schema, 'sources')),
            (created.id,),
        ).fetchone()[0]
    assert plaintext not in row_text


def test_mixed_runnable_sources_are_ordered_and_filtered(pg_registry):
    registry, _ = pg_registry
    configs = (
        _config(
            id='pve-b',
            source_instance='pve-b',
            legacy_identity_owner=False,
        ),
        _esxi_config('esxi-a'),
        _esxi_config('esxi-disabled', enabled=False),
        _esxi_config('esxi-sync-disabled', sync_enabled=False),
    )
    for config in configs:
        registry.create_source(config)

    runnable = registry.list_runnable_sources()

    assert [(config.id, config.source_type) for config in runnable] == [
        ('esxi-a', 'esxi'),
        ('pve-b', 'proxmox'),
    ]
