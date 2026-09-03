"""Stable SourceIdentity v2 domain behavior."""

from dataclasses import FrozenInstanceError

import pytest

from netbox_pve_sync.proxmox_discovery import discover_hosts
from netbox_pve_sync.source_identity import (
    SourceIdentity,
    host_source_identity,
    lxc_nic_source_identity,
    lxc_source_identity,
    qemu_nic_source_identity,
    qemu_source_identity,
)

from tests.fakes import FakeProxmox
from tests.sample_data import proxmox_responses, sample_source_config


def _host(node_name='node-a'):
    return discover_hosts(
        FakeProxmox(proxmox_responses(node_name)),
        sample_source_config(),
    )[0]


def test_identity_is_frozen_ordered_and_json_compatible():
    identity = qemu_source_identity(_host().virtual_machines[0])

    assert identity.to_record() == {
        'schema': 'v2',
        'type': 'proxmox',
        'instance': 'pve-infra-test',
        'kind': 'qemu',
        'external_id': '100',
    }
    assert SourceIdentity.from_record(identity.to_record()) == identity
    assert sorted([identity, host_source_identity(_host())])

    with pytest.raises(FrozenInstanceError):
        identity.external_id = '101'


def test_builders_distinguish_host_guest_and_nic_kinds():
    host = _host()
    vm = host.virtual_machines[0]
    container = host.containers[0]

    identities = {
        host_source_identity(host),
        qemu_source_identity(vm),
        lxc_source_identity(container),
        qemu_nic_source_identity(vm, vm.interfaces[0]),
        lxc_nic_source_identity(container, container.interfaces[0]),
    }

    assert {identity.kind for identity in identities} == {
        'host', 'qemu', 'lxc', 'qemu-nic', 'lxc-nic',
    }
    assert len(identities) == 5


def test_guest_and_nic_identities_survive_node_migration():
    before = _host('node-a')
    after = _host('node-b')

    before_vm = before.virtual_machines[0]
    after_vm = after.virtual_machines[0]
    before_lxc = before.containers[0]
    after_lxc = after.containers[0]

    assert qemu_source_identity(before_vm) == qemu_source_identity(after_vm)
    assert qemu_nic_source_identity(
        before_vm, before_vm.interfaces[0],
    ) == qemu_nic_source_identity(
        after_vm, after_vm.interfaces[0],
    )
    assert lxc_source_identity(before_lxc) == lxc_source_identity(after_lxc)
    assert lxc_nic_source_identity(
        before_lxc, before_lxc.interfaces[0],
    ) == lxc_nic_source_identity(
        after_lxc, after_lxc.interfaces[0],
    )


def test_source_instance_not_endpoint_participates_in_identity():
    first = discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config('old-pve.example'),
    )[0]
    second = discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config('new-pve.example'),
    )[0]

    assert qemu_source_identity(first.virtual_machines[0]) == (
        qemu_source_identity(second.virtual_machines[0])
    )
