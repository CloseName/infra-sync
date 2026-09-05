"""Migration catalog and fail-closed schema validation without PostgreSQL."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql


def _revision(revision='0001_registry_baseline'):
    return ScriptDirectory.from_config(Config('alembic.ini')).get_revision(revision).module


def _snapshot():
    expected = _revision().tables('infra_sync_test')
    columns = {
        table.name: [
            {'name': column.name, 'type': column.type, 'nullable': column.nullable,
             'default': str(column.server_default.arg) if column.server_default else None}
            for column in table.columns
        ]
        for table in expected
    }
    return expected, columns


def _inspector(columns):
    return SimpleNamespace(
        get_columns=lambda table, **_kw: columns[table],
        get_pk_constraint=lambda table, **_kw: {
            'constrained_columns': ['key' if table == 'schema_meta' else 'id'],
        },
        get_unique_constraints=lambda *_args, **_kw: [{'column_names': ['source_instance']}],
        get_check_constraints=lambda *_args, **_kw: [
            {'sqltext': "jsonb_typeof(settings) = 'object'::text"},
            {'sqltext': 'sync_interval_seconds > 0'},
        ],
    )


def test_catalog_has_single_forward_only_baseline():
    revision = _revision()
    assert revision.revision == '0001_registry_baseline'
    assert revision.down_revision is None
    with pytest.raises(RuntimeError, match='Downgrade'):
        revision.downgrade('infra_sync_test')


def test_history_revision_is_additive_and_forward_only():
    revision = _revision('head')
    assert revision.revision == '0002_sync_run_history'
    assert revision.down_revision == '0001_registry_baseline'
    with pytest.raises(RuntimeError, match='Downgrade'):
        revision.downgrade('infra_sync_test')


def test_legacy_snapshot_validates_without_writes(monkeypatch):
    expected, columns = _snapshot()
    monkeypatch.setattr(sa, 'inspect', lambda _connection: _inspector(columns))
    # Connection has no write method: validation must be inspection-only.
    _revision().validate(SimpleNamespace(dialect=postgresql.dialect()), expected)


@pytest.mark.parametrize('drift', ['missing', 'type', 'nullable', 'default', 'unique', 'check', 'pk'])
def test_legacy_drift_is_rejected(monkeypatch, drift):
    expected, original = _snapshot()
    columns = deepcopy(original)
    inspector = _inspector(columns)
    if drift == 'missing':
        columns['sources'].pop()
    elif drift == 'type':
        columns['sources'][0]['type'] = sa.Integer()
    elif drift == 'nullable':
        columns['sources'][0]['nullable'] = True
    elif drift == 'default':
        columns['sources'][0]['default'] = "'unexpected'::text"
    elif drift == 'unique':
        inspector.get_unique_constraints = lambda *_args, **_kw: []
    elif drift == 'check':
        inspector.get_check_constraints = lambda *_args, **_kw: []
    else:
        inspector.get_pk_constraint = lambda *_args, **_kw: {'constrained_columns': []}
    monkeypatch.setattr(sa, 'inspect', lambda _connection: inspector)
    with pytest.raises(RuntimeError, match='Legacy'):
        _revision().validate(SimpleNamespace(dialect=postgresql.dialect()), expected)


def test_offline_migration_is_rejected():
    with pytest.raises(ValueError, match='Offline'):
        command.upgrade(Config('alembic.ini'), 'head', sql=True)


def test_invalid_schema_fails_before_connection_use():
    config = Config('alembic.ini')
    config.attributes['schema'] = 'public; unsafe'
    config.attributes['connection'] = SimpleNamespace(dialect=postgresql.dialect())
    with pytest.raises(ValueError, match='safe explicit'):
        command.upgrade(config, 'head')
