"""Fail-closed behavior for ownership and matching conflicts."""

from copy import deepcopy

import pytest

from netbox_pve_sync.netbox_vm_apply import (
    VMApplyError,
    apply_virtual_machines,
)
from netbox_pve_sync.netbox_vm_network_apply import (
    VMNetworkApplyError,
    apply_vm_networks,
)
from netbox_pve_sync.proxmox_discovery import discover_hosts

from tests.fakes import FakeProxmox, FakeRecord
from tests.netbox_scenarios import add_target, vm_identity
from tests.sample_data import (
    proxmox_responses,
    sample_source_config,
)


def _hosts():
    return discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config(),
    )


def _netbox_vm(fake_netbox, cluster, **overrides):
    fields = {
        'id': 10,
        'name': 'qemu-100',
        'cluster': cluster,
        'tenant': None,
        'status': 'active',
        'vcpus': 4,
        'memory': 4096,
        'disk': 32768,
        'start_on_boot': 'on',
        'custom_fields': vm_identity(),
    }
    fields.update(overrides)
    return fake_netbox.virtualization.virtual_machines.add(
        FakeRecord(**fields)
    )


def test_duplicate_netbox_managed_identity_blocks_vm_apply(fake_netbox):
    _, _, cluster, config = add_target(fake_netbox)
    _netbox_vm(fake_netbox, cluster, id=10)
    _netbox_vm(fake_netbox, cluster, id=11, name='duplicate-object')

    with pytest.raises(VMApplyError, match='precheck failed'):
        apply_virtual_machines(
            fake_netbox,
            _hosts(),
            config,
            confirmed=True,
        )

    assert fake_netbox.mutations == []


def test_duplicate_discovered_identity_blocks_vm_apply(fake_netbox):
    _, _, _, config = add_target(fake_netbox)
    hosts = _hosts()
    hosts[0].virtual_machines.append(
        deepcopy(hosts[0].virtual_machines[0])
    )

    with pytest.raises(
        VMApplyError,
        match='Duplicate discovered VM identities',
    ):
        apply_virtual_machines(
            fake_netbox,
            hosts,
            config,
            confirmed=True,
        )

    assert fake_netbox.mutations == []


def test_identity_outside_target_cluster_blocks_vm_apply(fake_netbox):
    site, cluster_type, _, config = add_target(fake_netbox)
    other_cluster = fake_netbox.virtualization.clusters.add(
        FakeRecord(
            id=4,
            name='Other Cluster',
            type=cluster_type,
            scope_type='dcim.site',
            scope_id=site.id,
        )
    )
    _netbox_vm(fake_netbox, other_cluster)

    with pytest.raises(VMApplyError, match='precheck failed'):
        apply_virtual_machines(
            fake_netbox,
            _hosts(),
            config,
            confirmed=True,
        )

    assert fake_netbox.mutations == []


def test_name_only_adoption_candidate_blocks_vm_apply(fake_netbox):
    _, _, cluster, config = add_target(fake_netbox)
    _netbox_vm(
        fake_netbox,
        cluster,
        custom_fields={},
    )

    with pytest.raises(VMApplyError, match='precheck failed'):
        apply_virtual_machines(
            fake_netbox,
            _hosts(),
            config,
            confirmed=True,
        )

    assert fake_netbox.mutations == []


@pytest.mark.parametrize(
    ('endpoint_name', 'record_fields', 'message'),
    (
        (
            'mac_addresses',
            {
                'id': 20,
                'mac_address': 'AA:BB:CC:DD:EE:01',
                'assigned_object_type': 'dcim.interface',
                'assigned_object_id': 999,
            },
            'MAC AA:BB:CC:DD:EE:01 already assigned',
        ),
        (
            'ip_addresses',
            {
                'id': 21,
                'address': '10.20.30.40/24',
                'assigned_object_type': 'dcim.interface',
                'assigned_object_id': 999,
            },
            'IP 10.20.30.40/24 already assigned',
        ),
    ),
)
def test_occupied_network_object_blocks_before_write(
        fake_netbox,
        endpoint_name,
        record_fields,
        message,
):
    _, _, cluster, config = add_target(fake_netbox)
    _netbox_vm(fake_netbox, cluster)

    group = (
        fake_netbox.dcim
        if endpoint_name == 'mac_addresses'
        else fake_netbox.ipam
    )
    getattr(group, endpoint_name).add(
        FakeRecord(**record_fields)
    )

    with pytest.raises(VMNetworkApplyError, match=message):
        apply_vm_networks(
            fake_netbox,
            _hosts(),
            config,
            confirmed=True,
        )

    assert fake_netbox.mutations == []
