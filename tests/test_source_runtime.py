"""Runtime source selection and secret-resolution boundary tests."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from netbox_pve_sync.secret_resolver import (
    FileSecretResolver,
    SecretResolutionError,
)
from netbox_pve_sync.source_bootstrap import (
    SourceBootstrapError,
    load_runtime_source_config,
    load_runtime_source_configs,
    load_scheduler_source_configs,
    runtime_source_mode,
)
from netbox_pve_sync.source_config import SecretReference, SourceConfig

from tests.sample_data import sample_source_config
from tests.test_source_config import legacy_environment


class FakeRegistry:
    """Minimal read-only registry used by runtime selection tests."""

    def __init__(self, config):
        self.config = config
        self.requested_ids = []

    def get_source_config(self, source_id):
        self.requested_ids.append(source_id)
        return self.config

    def list_runnable_sources(self):
        return self.config


def registry_environment(**overrides):
    """Return explicit single-source registry runtime settings."""

    environ = {
        'SOURCE_CONFIG_MODE': 'registry',
        'INFRA_SYNC_REGISTRY_DSN': 'postgresql://registry.invalid/test',
        'INFRA_SYNC_REGISTRY_SCHEMA': 'infra_sync',
        'SOURCE_ID': 'pve-infra-test',
    }
    environ.update(overrides)
    return environ


def registry_all_environment(**overrides):
    """Return explicit multi-source registry runtime settings."""

    environ = registry_environment(SOURCE_CONFIG_MODE='registry-all')
    environ.pop('SOURCE_ID')
    environ.update(overrides)
    return environ


def test_absent_runtime_mode_preserves_legacy_default():
    environ = legacy_environment()

    config = load_runtime_source_config(environ)

    assert runtime_source_mode(environ) == 'legacy'
    assert isinstance(config, SourceConfig)
    assert config.source_instance == 'pve-infra-test'


def test_explicit_legacy_mode_uses_legacy_source_config():
    environ = legacy_environment(SOURCE_CONFIG_MODE='legacy')

    config = load_runtime_source_config(environ)

    assert isinstance(config, SourceConfig)
    assert config.address == 'pve.test.example'


@pytest.mark.parametrize('value', ('', 'unknown', ' legacy-ish '))
def test_explicit_invalid_runtime_mode_fails_closed(value):
    with pytest.raises(SourceBootstrapError, match='SOURCE_CONFIG_MODE'):
        runtime_source_mode({'SOURCE_CONFIG_MODE': value})


@pytest.mark.parametrize(
    'missing_variable',
    ('INFRA_SYNC_REGISTRY_DSN', 'INFRA_SYNC_REGISTRY_SCHEMA', 'SOURCE_ID'),
)
def test_registry_mode_requires_complete_explicit_selection(missing_variable):
    environ = registry_environment()
    environ.pop(missing_variable)

    with pytest.raises(SourceBootstrapError, match=missing_variable):
        load_runtime_source_config(environ)


def test_registry_mode_returns_canonical_source_config():
    expected = sample_source_config()
    registry = FakeRegistry(expected)
    received = []

    def factory(dsn, schema):
        received.append((dsn, schema))
        return registry

    config = load_runtime_source_config(
        registry_environment(),
        registry_factory=factory,
    )

    assert config is expected
    assert isinstance(config, SourceConfig)
    assert registry.requested_ids == ['pve-infra-test']
    assert received == [('postgresql://registry.invalid/test', 'infra_sync')]


def test_registry_all_loads_runnable_sources_without_source_id():
    expected = (sample_source_config(),)
    registry = FakeRegistry(expected)

    configs = load_runtime_source_configs(
        registry_all_environment(),
        registry_factory=lambda _dsn, _schema: registry,
    )

    assert configs == expected


def test_scheduler_reloads_new_and_disabled_sources_without_process_restart():
    registry = SimpleNamespace(configs=(sample_source_config(),))

    def list_isolated():
        return tuple(SimpleNamespace(
            valid=True,
            record=SimpleNamespace(to_source_config=lambda value=value: value),
        ) for value in registry.configs)

    registry.list_sources_isolated = list_isolated
    factory = lambda _dsn, _schema: registry
    first = load_scheduler_source_configs(
        registry_all_environment(), registry_factory=factory,
    )
    second_source = replace(
        sample_source_config(), id='esxi-b', source_instance='esxi-b',
        source_type='esxi', sync_enabled=False, legacy_identity_owner=False,
    )
    registry.configs = (replace(sample_source_config(), sync_enabled=False), second_source)
    second = load_scheduler_source_configs(
        registry_all_environment(), registry_factory=factory,
    )

    assert [item.config.source_instance for item in first] == ['pve-infra-test']
    assert [(item.config.source_instance, item.config.sync_enabled) for item in second] == [
        ('pve-infra-test', False), ('esxi-b', False),
    ]


def test_registry_all_selects_runnable_proxmox_and_esxi_sources():
    proxmox = sample_source_config()
    password = SecretReference(provider='file', key='esxi-password')
    esxi = replace(
        proxmox,
        id='esxi-a',
        source_instance='esxi-a',
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=replace(
            proxmox.credentials,
            token_id=password,
            token_secret=password,
        ),
    )
    registry = FakeRegistry((proxmox, esxi))

    configs = load_runtime_source_configs(
        registry_all_environment(),
        registry_factory=lambda _dsn, _schema: registry,
    )

    assert {config.source_type for config in configs} == {'proxmox', 'esxi'}


def test_registry_all_with_no_runnable_sources_fails_closed():
    registry = FakeRegistry(())

    with pytest.raises(SourceBootstrapError, match='no runnable sources'):
        load_runtime_source_configs(
            registry_all_environment(),
            registry_factory=lambda _dsn, _schema: registry,
        )


def test_registry_all_rejects_multiple_legacy_identity_owners():
    first = replace(
        sample_source_config(),
        id='pve-a',
        source_instance='pve-a',
        legacy_identity_owner=True,
    )
    second = replace(
        sample_source_config(),
        id='pve-b',
        source_instance='pve-b',
        legacy_identity_owner=True,
    )
    registry = FakeRegistry((first, second))

    with pytest.raises(SourceBootstrapError, match='legacy identity owners'):
        load_runtime_source_configs(
            registry_all_environment(),
            registry_factory=lambda _dsn, _schema: registry,
        )


def test_registry_all_unavailable_fails_before_source_execution():
    def unavailable(_dsn, _schema):
        raise RuntimeError('registry unavailable')

    with pytest.raises(RuntimeError, match='registry unavailable'):
        load_runtime_source_configs(
            registry_all_environment(),
            registry_factory=unavailable,
        )


def test_single_registry_mode_still_requires_source_id():
    environ = registry_environment()
    environ.pop('SOURCE_ID')

    with pytest.raises(SourceBootstrapError, match='SOURCE_ID'):
        load_runtime_source_config(environ)


@pytest.mark.parametrize(
    ('change', 'message'),
    (
        ({}, 'was not found'),
        ({'enabled': False}, 'is disabled'),
        ({'sync_enabled': False}, 'has sync disabled'),
    ),
)
def test_registry_selection_never_falls_back_to_legacy(change, message):
    config = None if not change else replace(sample_source_config(), **change)
    registry = FakeRegistry(config)

    with pytest.raises(SourceBootstrapError, match=message):
        load_runtime_source_config(
            registry_environment(),
            registry_factory=lambda _dsn, _schema: registry,
        )


def test_file_secret_resolver_uses_fixed_root_and_strips_value(tmp_path):
    (tmp_path / 'proxmox-token').write_text(' token-value\n', encoding='utf-8')
    resolver = FileSecretResolver(environ={}, secret_root=tmp_path)

    assert resolver.resolve(
        SecretReference(provider='file', key='proxmox-token')
    ) == 'token-value'


@pytest.mark.parametrize('key', ('../escape', '/absolute/path', r'folder\secret'))
def test_file_secret_resolver_rejects_paths(key, tmp_path):
    resolver = FileSecretResolver(environ={}, secret_root=tmp_path)

    with pytest.raises(SecretResolutionError, match='logical name'):
        resolver.resolve(SecretReference(provider='file', key=key))


def test_secret_resolution_errors_do_not_contain_secret_values():
    resolver = FileSecretResolver(environ={'TOKEN': '  '})

    with pytest.raises(SecretResolutionError) as error:
        resolver.resolve(SecretReference(provider='env', key='TOKEN'))

    assert 'secret-value' not in str(error.value)
