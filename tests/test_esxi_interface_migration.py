"""Confirmed ESXi legacy interface migration safety tests."""

from copy import deepcopy
from dataclasses import replace

import pytest

from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_interface_migration import (
    EsxiInterfaceMigrationError,
    apply_esxi_interface_migration,
)
from netbox_sync.esxi_migration import (
    InterfaceMigrationClassification,
    build_esxi_migration_plan,
)
from netbox_sync.netbox_metadata import build_device_custom_fields
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_sync.source_config import SecretReference, SourceCredentials
from netbox_sync.source_identity import SourceIdentity

from tests.fakes import FakeRecord
from tests.fakes.esxi import fake_esxi_service
from tests.netbox_scenarios import add_target
from tests.sample_data import sample_source_config


def _config():
    password = SecretReference(provider='env', key='ESXI_TEST_PASSWORD')
    return replace(
        sample_source_config(),
        id='esxi-infra-test',
        source_instance='esxi-infra-test',
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=SourceCredentials.for_password('root', password),
    )


def _inventory():
    service = fake_esxi_service(vm_name='APP-VM')
    network = service.host.vm[0].guest.net[0]
    network.ipConfig.ipAddress[0].ipAddress = '192.0.2.50'
    network.ipAddress = ['192.0.2.50']
    return discover_hosts(service, _config())


def _add_vm_interface(
        fake_netbox,
        vm,
        *,
        interface_id=20,
        name='legacy0',
        ip_address='192.0.2.50/24',
        custom_fields=None,
):
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=interface_id,
        name=name,
        virtual_machine=vm,
        custom_fields=custom_fields or {},
        description='operator note',
    ))
    ip_record = None
    if ip_address:
        ip_record = fake_netbox.ipam.ip_addresses.add(FakeRecord(
            id=1000 + interface_id,
            address=ip_address,
            assigned_object_type='virtualization.vminterface',
            assigned_object_id=interface.id,
        ))
    return interface, ip_record


def _managed_vm_setup(fake_netbox, *, with_interface=True):
    _, _, cluster, _ = add_target(fake_netbox)
    hosts = _inventory()
    discovered = hosts[0].virtual_machines[0]
    vm = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=10,
        name='LEGACY-APP',
        cluster=cluster,
        custom_fields=build_vm_custom_fields(discovered),
    ))
    interface = ip_record = None
    if with_interface:
        interface, ip_record = _add_vm_interface(
            fake_netbox,
            vm,
            custom_fields={'manual_key': 'keep'},
        )
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())
    return hosts, vm, interface, ip_record, plan


def _assert_no_writes(fake_netbox, plan):
    with pytest.raises(EsxiInterfaceMigrationError):
        apply_esxi_interface_migration(
            fake_netbox, plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_same_owner_vm_interface_is_reused_and_idempotent(fake_netbox):
    hosts, _, interface, ip_record, plan = _managed_vm_setup(fake_netbox)
    original_ip_id = ip_record.id

    assert apply_esxi_interface_migration(
        fake_netbox, plan, confirmed=True,
    ) == 1

    assert interface.id == 20
    assert interface.name == 'Network adapter 1'
    assert interface.description == 'operator note'
    assert interface.custom_fields['manual_key'] == 'keep'
    assert ip_record.id == original_ip_id
    assert ip_record.assigned_object_id == interface.id
    identities = [
        SourceIdentity.from_record(value)
        for value in interface.custom_fields['sync_identities']
    ]
    assert any(identity.kind == 'vm-nic' for identity in identities)

    fake_netbox.clear_mutations()
    fresh_plan = build_esxi_migration_plan(fake_netbox, hosts, _config())
    result = fresh_plan.virtual_machines[0].interfaces[0]
    assert result.classification == (
        InterfaceMigrationClassification.MATCH_EXISTING
    )
    assert apply_esxi_interface_migration(
        fake_netbox, fresh_plan, confirmed=True,
    ) == 0
    assert fake_netbox.mutations == []


def test_host_management_interface_is_reused(fake_netbox):
    site, _, cluster, _ = add_target(fake_netbox)
    hosts = _inventory()
    host = hosts[0]
    device = fake_netbox.dcim.devices.add(FakeRecord(
        id=13,
        name='ESXI-INFRA',
        site=site,
        cluster=cluster,
        custom_fields=build_device_custom_fields(host),
    ))
    interface = fake_netbox.dcim.interfaces.add(FakeRecord(
        id=22,
        name='wan',
        device=device,
        custom_fields={'manual_key': 'keep'},
    ))
    ip_record = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=1022,
        address='192.0.2.10/24',
        assigned_object_type='dcim.interface',
        assigned_object_id=interface.id,
    ))
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    assert apply_esxi_interface_migration(
        fake_netbox, plan, confirmed=True,
    ) == 1
    assert interface.id == 22
    assert interface.name == 'vmnic0'
    assert interface.custom_fields == {'manual_key': 'keep'}
    assert ip_record.id == 1022
    assert ip_record.assigned_object_id == interface.id


def test_desired_name_collision_blocks_all_writes(fake_netbox):
    _, vm, _, _, plan = _managed_vm_setup(fake_netbox)
    fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=21,
        name='Network adapter 1',
        virtual_machine=vm,
        custom_fields={},
    ))

    _assert_no_writes(fake_netbox, plan)


def test_foreign_ip_change_after_preflight_blocks_all_writes(fake_netbox):
    _, _, _, ip_record, plan = _managed_vm_setup(fake_netbox)
    _, _, cluster, _ = add_target(fake_netbox)
    foreign = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=11, name='FOREIGN', cluster=cluster, custom_fields={},
    ))
    foreign_interface, _ = _add_vm_interface(
        fake_netbox,
        foreign,
        interface_id=21,
        ip_address=None,
    )
    ip_record.assigned_object_id = foreign_interface.id

    _assert_no_writes(fake_netbox, plan)


def test_foreign_mac_after_preflight_blocks_all_writes(fake_netbox):
    hosts, _, _, _, plan = _managed_vm_setup(fake_netbox)
    _, _, cluster, _ = add_target(fake_netbox)
    foreign = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=11, name='FOREIGN', cluster=cluster, custom_fields={},
    ))
    foreign_interface, _ = _add_vm_interface(
        fake_netbox,
        foreign,
        interface_id=21,
        ip_address=None,
    )
    discovered_mac = hosts[0].virtual_machines[0].interfaces[0].mac_address
    fake_netbox.dcim.mac_addresses.add(FakeRecord(
        id=2021,
        mac_address=discovered_mac,
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=foreign_interface.id,
    ))

    _assert_no_writes(fake_netbox, plan)


def test_stale_candidate_name_blocks_all_writes(fake_netbox):
    _, _, interface, _, plan = _managed_vm_setup(fake_netbox)
    interface.name = 'changed-after-preflight'

    _assert_no_writes(fake_netbox, plan)


def test_shared_candidate_claim_is_never_applied(fake_netbox):
    hosts, _, _, _, _ = _managed_vm_setup(fake_netbox)
    second = deepcopy(hosts[0].virtual_machines[0].interfaces[0])
    second.name = 'Network adapter 2'
    second.external_id = '4001'
    hosts[0].virtual_machines[0].interfaces.append(second)
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    assert all(
        item.classification == InterfaceMigrationClassification.AMBIGUOUS
        for item in plan.virtual_machines[0].interfaces
    )
    assert apply_esxi_interface_migration(
        fake_netbox, plan, confirmed=True,
    ) == 0
    assert fake_netbox.mutations == []


def test_create_items_are_ignored(fake_netbox):
    _, _, _, _, plan = _managed_vm_setup(
        fake_netbox, with_interface=False,
    )

    assert plan.virtual_machines[0].interfaces[0].classification == (
        InterfaceMigrationClassification.CREATE
    )
    assert apply_esxi_interface_migration(
        fake_netbox, plan, confirmed=True,
    ) == 0
    assert fake_netbox.mutations == []


def test_unconfirmed_migration_writes_nothing(fake_netbox):
    _, _, _, _, plan = _managed_vm_setup(fake_netbox)

    with pytest.raises(EsxiInterfaceMigrationError, match='confirmation'):
        apply_esxi_interface_migration(fake_netbox, plan)
    assert fake_netbox.mutations == []


def test_unassigned_mac_is_attached_only_to_reused_interface(fake_netbox):
    hosts, _, interface, _, plan = _managed_vm_setup(fake_netbox)
    discovered_mac = hosts[0].virtual_machines[0].interfaces[0].mac_address
    mac_record = fake_netbox.dcim.mac_addresses.add(FakeRecord(
        id=2020,
        mac_address=discovered_mac,
        assigned_object_type=None,
        assigned_object_id=None,
    ))

    assert apply_esxi_interface_migration(
        fake_netbox, plan, confirmed=True,
    ) == 1
    assert mac_record.assigned_object_type == 'virtualization.vminterface'
    assert mac_record.assigned_object_id == interface.id
    assert interface.primary_mac_address == mac_record.id
