"""Fail-closed behavior for ownership and matching conflicts."""

from copy import deepcopy

import pytest

from netbox_pve_sync.netbox_vm_apply import (
    VMApplyError,
    apply_virtual_machines,
)
from netbox_pve_sync.netbox_apply import HostApplyError, _resolve_cluster, _resolve_device
from netbox_pve_sync.netbox_planner import _find_device_match
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
        name='QEMU-100',
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


def test_case_only_name_match_never_adopts_proxmox_host(fake_netbox):
    site, _, cluster, _ = add_target(fake_netbox)
    fake_netbox.dcim.devices.add(FakeRecord(
        id=20, name='node-a', site=site, cluster=cluster, custom_fields={},
    ))

    with pytest.raises(HostApplyError, match='adoption candidate'):
        _resolve_device(fake_netbox, _hosts()[0], site)

    assert fake_netbox.mutations == []


def test_legacy_host_planner_also_rejects_name_only_match():
    host = _hosts()[0]
    candidate = FakeRecord(id=20, name='node-a', custom_fields={})

    with pytest.raises(RuntimeError, match='adoption candidate'):
        _find_device_match({'devices': {'node-a': candidate}}, host)


def test_foreign_source_management_ip_never_adopts_proxmox_host(fake_netbox):
    site, _, cluster, _ = add_target(fake_netbox)
    foreign_identity = {
        'schema': 'v2', 'type': 'esxi', 'instance': 'esxi-b',
        'kind': 'host', 'external_id': 'ha-host',
    }
    candidate = fake_netbox.dcim.devices.add(FakeRecord(
        id=20, name='ESXI-B', site=site, cluster=cluster,
        primary_ip4='10.20.30.10/24',
        custom_fields={'sync_identities': [foreign_identity]},
    ))

    with pytest.raises(HostApplyError, match='management_ip'):
        _resolve_device(fake_netbox, _hosts()[0], site)

    assert candidate.custom_fields == {'sync_identities': [foreign_identity]}
    assert fake_netbox.mutations == []


@pytest.mark.parametrize(
    ('endpoint_name', 'record_fields', 'message'),
    (
        ('mac_addresses', {
            'id': 30, 'mac_address': 'AA:BB:CC:DD:EE:01',
            'assigned_object_type': 'virtualization.vminterface',
            'assigned_object_id': 900,
        }, 'MAC AA:BB:CC:DD:EE:01 already assigned'),
        ('ip_addresses', {
            'id': 31, 'address': '10.20.30.40/24',
            'assigned_object_type': 'virtualization.vminterface',
            'assigned_object_id': 900,
        }, 'IP 10.20.30.40/24 already assigned'),
    ),
)
def test_proxmox_never_steals_network_value_from_esxi_interface(
        fake_netbox, endpoint_name, record_fields, message):
    _, _, cluster, config = add_target(fake_netbox)
    _netbox_vm(fake_netbox, cluster)
    foreign_vm = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=90, name='esxi-vm', cluster=cluster, custom_fields={
            'sync_identities': [{
                'schema': 'v2', 'type': 'esxi', 'instance': 'esxi-b',
                'kind': 'vm', 'external_id': 'uuid-b',
            }],
        },
    ))
    fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=900, name='Network adapter 1', virtual_machine=foreign_vm,
        custom_fields={},
    ))
    endpoint = (fake_netbox.dcim.mac_addresses if endpoint_name == 'mac_addresses'
                else fake_netbox.ipam.ip_addresses)
    endpoint.add(FakeRecord(**record_fields))

    with pytest.raises(VMNetworkApplyError, match=message):
        apply_vm_networks(fake_netbox, _hosts(), config, confirmed=True)

    assert fake_netbox.mutations == []


def test_same_cluster_name_is_resolved_independently_in_each_site(fake_netbox):
    site_a = fake_netbox.dcim.sites.add(FakeRecord(id=101, slug='site-a'))
    site_b = fake_netbox.dcim.sites.add(FakeRecord(id=102, slug='site-b'))
    cluster_type = fake_netbox.virtualization.cluster_types.add(FakeRecord(
        id=103, slug='virtualization',
    ))
    cluster_a = fake_netbox.virtualization.clusters.add(FakeRecord(
        id=104, name='CLUSTER-X', type=cluster_type,
        scope_type='dcim.site', scope_id=site_a.id,
    ))
    cluster_b = fake_netbox.virtualization.clusters.add(FakeRecord(
        id=105, name='CLUSTER-X', type=cluster_type,
        scope_type='dcim.site', scope_id=site_b.id,
    ))

    assert _resolve_cluster(
        fake_netbox, site_a, cluster_type, 'CLUSTER-X',
    ) is cluster_a
    assert _resolve_cluster(
        fake_netbox, site_b, cluster_type, 'CLUSTER-X',
    ) is cluster_b


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
