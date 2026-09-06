"""Compatibility and validation tests for the single-source config boundary."""

from dataclasses import FrozenInstanceError

import pytest

from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.source_config import SourceConfig

from tests.fakes import FakeProxmox
from tests.sample_data import (
    proxmox_responses,
    sample_source_config,
)


def legacy_environment(**overrides):
    """Environment used by the current compose-based deployment."""

    environ = {
        'SOURCE_INSTANCE': 'pve-infra-test',
        'PVE_API_HOST': 'pve.test.example',
        'PVE_API_USER': 'sync@pve',
        'PVE_API_VERIFY_SSL': 'true',
        'PVE_API_TOKEN_FILE': '/run/secrets/proxmox_token_id',
        'PVE_API_SECRET_FILE': '/run/secrets/proxmox_token_secret',
        'NB_SITE_SLUG': 'test-site',
        'NB_DEVICE_ROLE_SLUG': 'server',
        'NB_PLATFORM_SLUG': 'proxmox',
        'NB_DEVICE_TYPE_SLUG': 'generic',
        'NB_CLUSTER_TYPE_SLUG': 'proxmox',
        'NB_CLUSTER_NAME': 'Test Cluster',
    }
    environ.update(overrides)
    return environ


def test_legacy_environment_builds_one_immutable_source_config():
    config = SourceConfig.from_legacy_environment(
        legacy_environment()
    )

    assert config.id == 'pve-infra-test'
    assert config.source_instance == 'pve-infra-test'
    assert config.name == 'pve-infra-test'
    assert config.source_type == 'proxmox'
    assert config.address == 'pve.test.example'
    assert config.enabled is True
    assert config.sync_enabled is True
    assert config.sync_interval_seconds == 600
    assert config.verify_ssl is True
    assert config.target.site_slug == 'test-site'
    assert config.target.cluster_name == 'Test Cluster'
    assert config.credentials.username == 'sync@pve'
    assert config.credentials.token_id.provider == 'file'
    assert config.credentials.token_id.key == (
        '/run/secrets/proxmox_token_id'
    )

    with pytest.raises(FrozenInstanceError):
        config.address = 'changed.example'

    with pytest.raises(TypeError):
        config.settings['key'] = 'value'


@pytest.mark.parametrize(
    'source_instance',
    (
        '',
        'PVE-PROD',
        'pve prod',
        'https://pve.example',
        'user:password@pve',
        'x' * 64,
    ),
)
def test_invalid_source_instance_fails_closed(source_instance):
    with pytest.raises(ValueError, match='SOURCE_INSTANCE|source_instance'):
        SourceConfig.from_legacy_environment(
            legacy_environment(
                SOURCE_INSTANCE=source_instance,
            )
        )


def test_source_instance_does_not_depend_on_proxmox_address():
    first = SourceConfig.from_legacy_environment(
        legacy_environment(
            PVE_API_HOST='old-pve.test.example',
        )
    )
    second = SourceConfig.from_legacy_environment(
        legacy_environment(
            PVE_API_HOST='new-pve.test.example',
        )
    )

    assert first.address != second.address
    assert first.source_instance == second.source_instance
    assert first.source_instance == 'pve-infra-test'


def test_direct_legacy_secret_values_are_kept_out_of_config():
    environ = legacy_environment(
        PVE_API_TOKEN='token-name-value',
        PVE_API_SECRET='super-secret-value',
    )
    environ.pop('PVE_API_TOKEN_FILE')
    environ.pop('PVE_API_SECRET_FILE')

    config = SourceConfig.from_legacy_environment(environ)

    assert config.credentials.token_id.provider == 'environment'
    assert config.credentials.token_id.key == 'PVE_API_TOKEN'
    assert config.credentials.token_secret.key == 'PVE_API_SECRET'
    assert 'token-name-value' not in repr(config)
    assert 'super-secret-value' not in repr(config)


def test_discovery_propagates_source_instance_without_changing_v1_ids():
    config = sample_source_config()
    host = discover_hosts(
        FakeProxmox(proxmox_responses()),
        config,
    )[0]
    vm = host.virtual_machines[0]
    container = host.containers[0]

    assert host.source_instance == 'pve-infra-test'
    assert vm.source_instance == 'pve-infra-test'
    assert container.source_instance == 'pve-infra-test'

    # PHASE 2A deliberately preserves existing NetBox identity inputs.
    assert host.source == 'proxmox'
    assert host.source_id == 'node-a'
    assert vm.source_id == 'proxmox:node-a:100'
    assert container.source_id == 'proxmox:node-a:lxc:100'
