"""Read-only ESXi legacy object and network migration diagnostics."""

from copy import deepcopy
from dataclasses import replace

from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_migration import (
    InterfaceMigrationClassification,
    ObjectMigrationClassification,
    build_esxi_migration_plan,
)
from netbox_sync.netbox_metadata import build_device_custom_fields
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_sync.source_config import SecretReference, SourceCredentials

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


def _inventory(
        name='APP-VM',
        ip_address='192.0.2.50',
        vm_uuid='503c5ad7-0000-1111-2222-0123456789ab',
):
    service = fake_esxi_service(vm_name=name)
    vm = service.host.vm[0]
    vm.config.instanceUuid = vm_uuid
    network = vm.guest.net[0]
    network.ipConfig.ipAddress[0].ipAddress = ip_address
    network.ipAddress = [ip_address]
    return discover_hosts(service, _config())


def _target(fake_netbox):
    site, _, cluster, _ = add_target(fake_netbox)
    return site, cluster


def _add_vm(fake_netbox, cluster, record_id, name, custom_fields=None):
    return fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=record_id,
        name=name,
        cluster=cluster,
        custom_fields=custom_fields or {},
    ))


def _add_vm_interface(
        fake_netbox,
        vm,
        *,
        interface_id,
        name='legacy0',
        ip_address=None,
        mac_address=None,
):
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=interface_id,
        name=name,
        virtual_machine=vm,
        custom_fields={},
    ))
    if ip_address:
        fake_netbox.ipam.ip_addresses.add(FakeRecord(
            id=1000 + interface_id,
            address=ip_address,
            assigned_object_type='virtualization.vminterface',
            assigned_object_id=interface.id,
        ))
    if mac_address:
        fake_netbox.dcim.mac_addresses.add(FakeRecord(
            id=2000 + interface_id,
            mac_address=mac_address,
            assigned_object_type='virtualization.vminterface',
            assigned_object_id=interface.id,
        ))
    return interface


def _managed_vm(fake_netbox, cluster, hosts):
    discovered = hosts[0].virtual_machines[0]
    return _add_vm(
        fake_netbox,
        cluster,
        10,
        'LEGACY-APP',
        build_vm_custom_fields(discovered),
    )


def _vm_result(fake_netbox, hosts):
    return build_esxi_migration_plan(
        fake_netbox, hosts, _config(),
    ).virtual_machines[0]


def test_managed_vm_same_ip_on_legacy_interface_is_safe_reuse(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    managed = _managed_vm(fake_netbox, cluster, hosts)
    _add_vm_interface(
        fake_netbox,
        managed,
        interface_id=20,
        name='legacy-ethernet',
        ip_address='192.0.2.50/24',
    )

    result = _vm_result(fake_netbox, hosts)
    interface = result.interfaces[0]

    assert result.classification == ObjectMigrationClassification.MANAGED
    assert interface.classification == (
        InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE
    )
    assert interface.candidates[0].interface_id == 20
    assert interface.candidates[0].interface_name == 'legacy-ethernet'
    assert interface.candidates[0].current_ips == ('192.0.2.50',)
    assert interface.candidates[0].signals == ('ip:192.0.2.50',)


def test_managed_vm_ip_owned_by_another_vm_is_conflict(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    _managed_vm(fake_netbox, cluster, hosts)
    other = _add_vm(fake_netbox, cluster, 11, 'OTHER-VM')
    _add_vm_interface(
        fake_netbox,
        other,
        interface_id=21,
        ip_address='192.0.2.50/24',
    )

    interface = _vm_result(fake_netbox, hosts).interfaces[0]

    assert interface.classification == InterfaceMigrationClassification.CONFLICT
    assert interface.candidates[0].parent_id == 11
    assert interface.candidates[0].conflicts == ('foreign_parent',)


def test_duplicate_ip_assignments_are_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    managed = _managed_vm(fake_netbox, cluster, hosts)
    interface = _add_vm_interface(
        fake_netbox,
        managed,
        interface_id=20,
        ip_address='192.0.2.50/24',
    )
    fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=1021,
        address='192.0.2.50/24',
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=interface.id,
    ))

    result = _vm_result(fake_netbox, hosts).interfaces[0]

    assert result.classification == InterfaceMigrationClassification.AMBIGUOUS
    assert result.conflicts == ('duplicate network evidence',)


def test_unassigned_ip_is_not_reported_as_foreign_conflict(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    _managed_vm(fake_netbox, cluster, hosts)
    fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=1020,
        address='192.0.2.50/24',
        assigned_object_type=None,
        assigned_object_id=None,
    ))

    result = _vm_result(fake_netbox, hosts).interfaces[0]

    assert result.classification == InterfaceMigrationClassification.CREATE
    assert result.conflicts == ()


def test_unique_mac_on_managed_vm_is_safe_reuse(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    managed = _managed_vm(fake_netbox, cluster, hosts)
    _add_vm_interface(
        fake_netbox,
        managed,
        interface_id=20,
        name='legacy-ethernet',
        mac_address='00:50:56:AA:BB:CC',
    )

    interface = _vm_result(fake_netbox, hosts).interfaces[0]

    assert interface.classification == (
        InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE
    )
    assert interface.candidates[0].current_macs == ('00:50:56:AA:BB:CC',)
    assert interface.candidates[0].signals == ('mac:00:50:56:AA:BB:CC',)


def test_host_management_ip_is_safe_legacy_interface_candidate(fake_netbox):
    site, cluster = _target(fake_netbox)
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
        id=30,
        name='management',
        device=device,
        custom_fields={},
    ))
    fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=1030,
        address='192.0.2.10/24',
        assigned_object_type='dcim.interface',
        assigned_object_id=interface.id,
    ))

    result = build_esxi_migration_plan(
        fake_netbox, hosts, _config(),
    ).hosts[0].interfaces[0]

    assert result.classification == (
        InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE
    )
    assert result.candidates[0].interface_id == 30
    assert result.candidates[0].current_ips == ('192.0.2.10',)


def test_management_ip_only_correlates_deterministic_uplink(fake_netbox):
    site, cluster = _target(fake_netbox)
    service = fake_esxi_service()
    second_pnic = deepcopy(service.host.config.network.pnic[0])
    second_pnic.key = 'key-vim.host.PhysicalNic-vmnic1'
    second_pnic.device = 'vmnic1'
    second_pnic.mac = '00:11:22:33:44:66'
    service.host.config.network.pnic.append(second_pnic)
    hosts = discover_hosts(service, _config())
    host = hosts[0]
    device = fake_netbox.dcim.devices.add(FakeRecord(
        id=13,
        name='ESXI-INFRA',
        site=site,
        cluster=cluster,
        custom_fields=build_device_custom_fields(host),
    ))
    interface = fake_netbox.dcim.interfaces.add(FakeRecord(
        id=30,
        name='management',
        device=device,
        custom_fields={},
    ))
    fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=1030,
        address='192.0.2.10/24',
        assigned_object_type='dcim.interface',
        assigned_object_id=interface.id,
    ))

    results = build_esxi_migration_plan(
        fake_netbox, hosts, _config(),
    ).hosts[0].interfaces

    by_name = {item.discovered_name: item for item in results}
    assert by_name['vmnic0'].classification == (
        InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE
    )
    assert by_name['vmnic1'].classification == (
        InterfaceMigrationClassification.CREATE
    )


def test_two_discovered_nics_claiming_one_interface_are_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    managed = _managed_vm(fake_netbox, cluster, hosts)
    _add_vm_interface(
        fake_netbox,
        managed,
        interface_id=20,
        name='legacy-ethernet',
        ip_address='192.0.2.50/24',
    )
    second_nic = deepcopy(hosts[0].virtual_machines[0].interfaces[0])
    second_nic.name = 'Network adapter 2'
    second_nic.external_id = '4001'
    hosts[0].virtual_machines[0].interfaces.append(second_nic)

    interfaces = _vm_result(fake_netbox, hosts).interfaces

    assert len(interfaces) == 2
    assert all(
        item.classification == InterfaceMigrationClassification.AMBIGUOUS
        for item in interfaces
    )
    assert all('shared interface claim' in item.conflicts for item in interfaces)


def test_exact_name_only_unmatched_vm_requires_review(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(fake_netbox, cluster, 10, 'app-vm')

    result = _vm_result(fake_netbox, _inventory())

    assert result.classification == ObjectMigrationClassification.REVIEW_REQUIRED
    assert result.candidates[0].signals == ('exact_name',)


def test_unmatched_vm_with_unique_ip_is_safe_legacy_candidate(fake_netbox):
    _, cluster = _target(fake_netbox)
    legacy = _add_vm(fake_netbox, cluster, 10, 'RENAMED-LEGACY')
    _add_vm_interface(
        fake_netbox,
        legacy,
        interface_id=20,
        ip_address='192.0.2.50/24',
    )

    result = _vm_result(fake_netbox, _inventory())

    assert result.classification == (
        ObjectMigrationClassification.SAFE_LEGACY_CANDIDATE
    )
    assert result.candidates[0].signals == ('ip:192.0.2.50',)


def test_unmatched_vm_without_evidence_is_new(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(fake_netbox, cluster, 10, 'UNRELATED')

    result = _vm_result(fake_netbox, _inventory())

    assert result.classification == ObjectMigrationClassification.NEW
    assert result.candidates == ()


def test_multiple_legacy_vms_sharing_ip_are_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    for record_id in (10, 11):
        legacy = _add_vm(fake_netbox, cluster, record_id, f'LEGACY-{record_id}')
        _add_vm_interface(
            fake_netbox,
            legacy,
            interface_id=record_id + 20,
            ip_address='192.0.2.50/24',
        )

    result = _vm_result(fake_netbox, _inventory())

    assert result.classification == ObjectMigrationClassification.AMBIGUOUS
    assert {candidate.object_id for candidate in result.candidates} == {10, 11}


def test_existing_esxi_v2_object_is_not_reused_as_legacy(fake_netbox):
    _, cluster = _target(fake_netbox)
    other_hosts = _inventory(
        name='OTHER-LIVE',
        vm_uuid='503c5ad7-aaaa-bbbb-cccc-0123456789ab',
    )
    other_vm = other_hosts[0].virtual_machines[0]
    existing = _add_vm(
        fake_netbox,
        cluster,
        10,
        'OLD-MANAGED',
        build_vm_custom_fields(other_vm),
    )
    _add_vm_interface(
        fake_netbox,
        existing,
        interface_id=20,
        ip_address='192.0.2.50/24',
    )

    result = _vm_result(fake_netbox, _inventory())

    assert result.classification == ObjectMigrationClassification.AMBIGUOUS
    assert result.candidates[0].conflicts == ('existing_managed_identity',)


def test_migration_planner_performs_zero_writes(fake_netbox):
    _, cluster = _target(fake_netbox)
    legacy = _add_vm(fake_netbox, cluster, 10, 'RENAMED-LEGACY')
    _add_vm_interface(
        fake_netbox,
        legacy,
        interface_id=20,
        ip_address='192.0.2.50/24',
    )

    plan = build_esxi_migration_plan(
        fake_netbox, _inventory(), _config(),
    )

    assert plan.virtual_machines[0].classification == (
        ObjectMigrationClassification.SAFE_LEGACY_CANDIDATE
    )
    assert fake_netbox.mutations == []
