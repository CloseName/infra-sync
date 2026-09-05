"""Stable SourceIdentity v2 domain behavior."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from netbox_pve_sync.proxmox_discovery import discover_hosts
from netbox_pve_sync.netbox_vm_interface_metadata import (
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
)
from netbox_pve_sync.source_identity import (
    SourceIdentity,
    host_source_identity,
    lxc_nic_source_identity,
    lxc_source_identity,
    qemu_nic_source_identity,
    qemu_source_identity,
)

from tests.fakes import FakeProxmox, FakeRecord
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


def test_same_node_name_is_namespaced_by_source_instance():
    first = _host()
    second_config = replace(
        sample_source_config(), id='pve-other', source_instance='pve-other',
        legacy_identity_owner=False,
    )
    second = discover_hosts(
        FakeProxmox(proxmox_responses()), second_config,
    )[0]

    assert first.original_name == second.original_name == 'node-a'
    assert host_source_identity(first) != host_source_identity(second)


def test_qemu_lxc_rename_and_node_move_keep_workload_identities():
    before_responses = proxmox_responses('node-a')
    after_responses = proxmox_responses('node-b')
    after_responses[('nodes', 'node-b', 'qemu')][0]['name'] = 'RENAMED-QEMU'
    after_responses[('nodes', 'node-b', 'lxc', 100, 'config')]['hostname'] = (
        'renamed-lxc'
    )
    before = discover_hosts(
        FakeProxmox(before_responses), sample_source_config(),
    )[0]
    after = discover_hosts(
        FakeProxmox(after_responses), sample_source_config(),
    )[0]

    assert qemu_source_identity(before.virtual_machines[0]) == (
        qemu_source_identity(after.virtual_machines[0])
    )
    assert lxc_source_identity(before.containers[0]) == (
        lxc_source_identity(after.containers[0])
    )


def test_same_vmids_and_names_are_isolated_by_source_and_kind():
    first_config = replace(
        sample_source_config(), id='pve-a', source_instance='pve-a',
        legacy_identity_owner=False,
    )
    second_config = replace(
        sample_source_config(), id='pve-b', source_instance='pve-b',
        legacy_identity_owner=False,
    )
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu')][0]['name'] = 'APP01'
    responses[('nodes', 'node-a', 'lxc', 100, 'config')]['hostname'] = 'APP01'
    first = discover_hosts(FakeProxmox(deepcopy(responses)), first_config)[0]
    second = discover_hosts(FakeProxmox(deepcopy(responses)), second_config)[0]

    assert first.virtual_machines[0].original_name == 'APP01'
    assert first.containers[0].original_name == 'APP01'
    assert qemu_source_identity(first.virtual_machines[0]) != (
        qemu_source_identity(second.virtual_machines[0])
    )
    assert lxc_source_identity(first.containers[0]) != (
        lxc_source_identity(second.containers[0])
    )
    assert qemu_source_identity(first.virtual_machines[0]) != (
        lxc_source_identity(first.containers[0])
    )


def test_nic_identity_uses_net_key_not_mutable_config_values():
    before_responses = proxmox_responses()
    after_responses = proxmox_responses()
    after_responses[('nodes', 'node-a', 'qemu', 100, 'config')]['net0'] = (
        'virtio=AA:BB:CC:DD:EE:99,bridge=vmbr9,tag=265'
    )
    after_responses[('nodes', 'node-a', 'lxc', 100, 'config')]['net0'] = (
        'name=renamed0,bridge=vmbr9,hwaddr=AA:BB:CC:DD:EE:98,'
        'ip=10.20.30.51/24,tag=266'
    )
    before = discover_hosts(
        FakeProxmox(before_responses), sample_source_config(),
    )[0]
    after = discover_hosts(
        FakeProxmox(after_responses), sample_source_config(),
    )[0]

    assert qemu_nic_source_identity(
        before.virtual_machines[0], before.virtual_machines[0].interfaces[0],
    ) == qemu_nic_source_identity(
        after.virtual_machines[0], after.virtual_machines[0].interfaces[0],
    )
    assert lxc_nic_source_identity(
        before.containers[0], before.containers[0].interfaces[0],
    ) == lxc_nic_source_identity(
        after.containers[0], after.containers[0].interfaces[0],
    )
    assert lxc_nic_source_identity(
        after.containers[0], after.containers[0].interfaces[0],
    ).external_id == '100:net0'


def test_lxc_nic_old_name_based_v2_identity_is_read_then_migrated_to_net_key():
    container = _host().containers[0]
    nic = container.interfaces[0]
    old_identity = SourceIdentity(
        schema='v2', type='proxmox', instance='pve-infra-test',
        kind='lxc-nic', external_id='100:eth0',
    )
    record = FakeRecord(id=10, custom_fields={
        'sync_identities': [old_identity.to_record()],
        'sync_original_names': {},
        'operator_note': 'keep',
    })

    assert find_nic_sync_identity_matches([record], container, nic) == [record]
    migrated = build_nic_custom_fields(container, nic, record.custom_fields)

    assert old_identity.to_record() not in migrated['sync_identities']
    assert lxc_nic_source_identity(container, nic).to_record() in (
        migrated['sync_identities']
    )
    assert migrated['operator_note'] == 'keep'


def test_old_lxc_nic_identity_from_other_source_is_not_a_match():
    container = _host().containers[0]
    nic = container.interfaces[0]
    foreign_identity = SourceIdentity(
        schema='v2', type='proxmox', instance='pve-other',
        kind='lxc-nic', external_id='100:eth0',
    )
    record = FakeRecord(id=10, custom_fields={
        'sync_identities': [foreign_identity.to_record()],
    })

    assert find_nic_sync_identity_matches([record], container, nic) == []


def test_multiple_nic_keys_are_stable_when_one_is_removed_and_restored():
    responses = proxmox_responses()
    qemu_config = responses[('nodes', 'node-a', 'qemu', 100, 'config')]
    qemu_config['net1'] = 'virtio=AA:BB:CC:DD:EE:11,bridge=vmbr1,tag=121'
    first = discover_hosts(
        FakeProxmox(responses), sample_source_config(),
    )[0].virtual_machines[0]
    first_by_key = {
        nic.external_id: qemu_nic_source_identity(first, nic)
        for nic in first.interfaces
    }

    removed = deepcopy(responses)
    removed[('nodes', 'node-a', 'qemu', 100, 'config')].pop('net0')
    without_net0 = discover_hosts(
        FakeProxmox(removed), sample_source_config(),
    )[0].virtual_machines[0]
    restored = discover_hosts(
        FakeProxmox(responses), sample_source_config(),
    )[0].virtual_machines[0]
    restored_by_key = {
        nic.external_id: qemu_nic_source_identity(restored, nic)
        for nic in restored.interfaces
    }

    assert [nic.external_id for nic in without_net0.interfaces] == ['net1']
    assert first_by_key['net0'] == restored_by_key['net0']
    assert first_by_key['net0'] != first_by_key['net1']
