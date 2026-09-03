"""Controlled creation tests for ESXi VMs classified NEW."""

from copy import deepcopy
from dataclasses import replace

import pytest

from netbox_pve_sync.esxi_discovery import discover_hosts
from netbox_pve_sync.esxi_migration import (
    ObjectMigrationClassification,
    build_esxi_migration_plan,
)
from netbox_pve_sync.esxi_vm_bootstrap import (
    EsxiNewVmBootstrapError,
    apply_esxi_new_vm_bootstrap,
)
from netbox_pve_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_pve_sync.source_config import SecretReference, SourceCredentials

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


def _inventory(count=1):
    hosts = discover_hosts(fake_esxi_service(vm_name='APP-1'), _config())
    first = hosts[0].virtual_machines[0]
    first.interfaces[0].ip_addresses = ['192.0.2.51/24']
    if count > 1:
        second = deepcopy(first)
        second.external_id = '503c5ad7-aaaa-bbbb-cccc-0123456789ab'
        second.vmid = second.external_id
        second.source_id = f'esxi:{second.external_id}'
        second.original_name = 'APP-2'
        second.normalized_name = second.original_name
        second.interfaces[0].mac_address = '00:50:56:AA:BB:CD'
        second.interfaces[0].ip_addresses = ['192.0.2.52/24']
        hosts[0].virtual_machines.append(second)
    return hosts


def _setup(fake_netbox, *, count=1):
    _, _, cluster, _ = add_target(fake_netbox)
    hosts = _inventory(count)
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())
    return cluster, hosts, plan


def _add_vm(fake_netbox, cluster, record_id, name, custom_fields=None):
    return fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=record_id,
        name=name,
        cluster=cluster,
        custom_fields=custom_fields or {},
        comments='operator-owned note',
    ))


def _add_primary_ip(fake_netbox, vm, record_id, address):
    ip_record = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=record_id,
        address=address,
        assigned_object_type=None,
        assigned_object_id=None,
    ))
    vm.primary_ip4 = ip_record
    return ip_record


def test_new_vm_creation_uses_shared_fields_v2_and_is_idempotent(fake_netbox):
    _, hosts, plan = _setup(fake_netbox)

    created_ids = apply_esxi_new_vm_bootstrap(
        fake_netbox, hosts, _config(), plan, confirmed=True,
    )

    assert created_ids == (1,)
    created = fake_netbox.virtualization.virtual_machines.get(id=1)
    assert created.name == 'APP-1'
    assert created.status == 'active'
    assert created.vcpus == 4
    assert created.memory == 8192
    assert created.disk == 20480
    assert created.start_on_boot == 'on'
    assert created.custom_fields['sync_identities'] == [{
        'schema': 'v2',
        'type': 'esxi',
        'instance': 'esxi-infra-test',
        'kind': 'vm',
        'external_id': hosts[0].virtual_machines[0].external_id,
    }]
    assert fake_netbox.virtualization.interfaces.all() == []
    assert fake_netbox.dcim.mac_addresses.all() == []

    fake_netbox.clear_mutations()
    fresh = build_esxi_migration_plan(fake_netbox, hosts, _config())
    assert fresh.virtual_machines[0].classification == (
        ObjectMigrationClassification.MANAGED
    )
    assert apply_esxi_new_vm_bootstrap(
        fake_netbox, hosts, _config(), fresh, confirmed=True,
    ) == ()
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('classification', [
    ObjectMigrationClassification.REVIEW_REQUIRED,
    ObjectMigrationClassification.MANAGED,
    ObjectMigrationClassification.SAFE_LEGACY_CANDIDATE,
    ObjectMigrationClassification.AMBIGUOUS,
])
def test_non_new_classifications_are_isolated(
        fake_netbox,
        classification,
):
    cluster, hosts, _ = _setup(fake_netbox, count=2)
    first = hosts[0].virtual_machines[0]
    if classification == ObjectMigrationClassification.REVIEW_REQUIRED:
        existing = _add_vm(fake_netbox, cluster, 10, first.original_name)
    elif classification == ObjectMigrationClassification.MANAGED:
        existing = _add_vm(
            fake_netbox,
            cluster,
            10,
            'OLD-MANAGED-NAME',
            build_vm_custom_fields(first),
        )
    elif classification == ObjectMigrationClassification.SAFE_LEGACY_CANDIDATE:
        existing = _add_vm(fake_netbox, cluster, 10, 'LEGACY-NAME')
        _add_primary_ip(fake_netbox, existing, 1010, '192.0.2.51/24')
    else:
        existing = _add_vm(fake_netbox, cluster, 10, first.original_name)
        _add_vm(fake_netbox, cluster, 11, first.original_name)
    original_fields = deepcopy(existing.__dict__)
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    assert plan.virtual_machines[0].classification == classification
    created_ids = apply_esxi_new_vm_bootstrap(
        fake_netbox, hosts, _config(), plan, confirmed=True,
    )

    assert len(created_ids) == 1
    assert fake_netbox.virtualization.virtual_machines.get(
        id=created_ids[0]
    ).name == 'APP-2'
    assert existing.name == original_fields['name']
    assert existing.custom_fields == original_fields['custom_fields']
    assert existing.comments == 'operator-owned note'


def test_stale_new_becoming_review_blocks_every_create(fake_netbox):
    cluster, hosts, plan = _setup(fake_netbox, count=2)
    _add_vm(fake_netbox, cluster, 10, 'APP-2')

    with pytest.raises(EsxiNewVmBootstrapError, match='stale'):
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_stale_new_gaining_identity_blocks_every_create(fake_netbox):
    cluster, hosts, plan = _setup(fake_netbox, count=2)
    second = hosts[0].virtual_machines[1]
    _add_vm(
        fake_netbox,
        cluster,
        10,
        'EXISTING-MANAGED',
        build_vm_custom_fields(second),
    )

    with pytest.raises(EsxiNewVmBootstrapError, match='stale'):
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_duplicate_discovered_identity_blocks_every_create(fake_netbox):
    _, hosts, plan = _setup(fake_netbox)
    duplicate = deepcopy(hosts[0].virtual_machines[0])
    duplicate.original_name = 'DUPLICATE-ID'
    duplicate.normalized_name = duplicate.original_name
    hosts[0].virtual_machines.append(duplicate)

    with pytest.raises(EsxiNewVmBootstrapError, match='Duplicate discovered'):
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_duplicate_selected_names_block_every_create(fake_netbox):
    _, hosts, _ = _setup(fake_netbox, count=2)
    hosts[0].virtual_machines[1].original_name = 'app-1'
    hosts[0].virtual_machines[1].normalized_name = 'app-1'
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    with pytest.raises(EsxiNewVmBootstrapError, match='duplicate NEW VM names'):
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_duplicate_target_name_after_preflight_blocks_every_create(fake_netbox):
    cluster, hosts, plan = _setup(fake_netbox)
    _add_vm(fake_netbox, cluster, 10, 'APP-1')
    _add_vm(fake_netbox, cluster, 11, 'app-1')

    with pytest.raises(EsxiNewVmBootstrapError, match='stale'):
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_all_create_fields_are_validated_before_first_create(fake_netbox):
    _, hosts, plan = _setup(fake_netbox, count=2)
    hosts[0].virtual_machines[1].status = 'unsupported-live-state'

    with pytest.raises(EsxiNewVmBootstrapError, match='create fields'):
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert fake_netbox.mutations == []


def test_unconfirmed_bootstrap_writes_nothing(fake_netbox):
    _, hosts, plan = _setup(fake_netbox)

    with pytest.raises(EsxiNewVmBootstrapError, match='confirmation'):
        apply_esxi_new_vm_bootstrap(fake_netbox, hosts, _config(), plan)
    assert fake_netbox.mutations == []


def test_api_failure_reports_ids_already_created(fake_netbox, monkeypatch):
    _, hosts, plan = _setup(fake_netbox, count=2)
    endpoint = fake_netbox.virtualization.virtual_machines
    original_create = endpoint.create
    calls = 0

    def fail_second_create(**fields):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('simulated NetBox failure')
        return original_create(**fields)

    monkeypatch.setattr(endpoint, 'create', fail_second_create)

    with pytest.raises(EsxiNewVmBootstrapError) as raised:
        apply_esxi_new_vm_bootstrap(
            fake_netbox, hosts, _config(), plan, confirmed=True,
        )
    assert raised.value.created_vm_ids == (1,)
    assert [record.name for record in endpoint.all()] == ['APP-1']
