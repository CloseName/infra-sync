"""Migration compatibility and fail-closed SourceIdentity v2 behavior."""

from dataclasses import replace

from netbox_sync.netbox_disappearance import report_missing_managed_objects
from netbox_sync.netbox_vm_apply import apply_virtual_machines
from netbox_sync.netbox_vm_metadata import (
    build_vm_custom_fields,
    find_vm_sync_identity_matches,
    matches_vm_sync_identity,
)
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.source_identity import qemu_source_identity

from tests.fakes import FakeProxmox, FakeRecord
from tests.netbox_scenarios import add_target, vm_identity
from tests.sample_data import proxmox_responses, sample_source_config


def _hosts(node_name='node-a'):
    return discover_hosts(
        FakeProxmox(proxmox_responses(node_name)),
        sample_source_config(),
    )


def _record(record_id, cluster, custom_fields, name=None):
    return FakeRecord(
        id=record_id,
        name=name or f'vm-{record_id}',
        cluster=cluster,
        tenant=None,
        status='active',
        vcpus=4,
        memory=4096,
        disk=32768,
        start_on_boot='on',
        custom_fields=custom_fields,
    )


def test_new_objects_write_v2_only_and_source_aware_original_name():
    vm = _hosts()[0].virtual_machines[0]

    fields = build_vm_custom_fields(vm)

    assert fields['sync_identities'] == [qemu_source_identity(vm).to_record()]
    assert fields['sync_original_names'] == {
        'proxmox/pve-infra-test/qemu': 'qemu-100',
    }


def test_legacy_match_requires_explicit_owner_and_migration_preserves_metadata():
    vm = _hosts()[0].virtual_machines[0]
    legacy = vm_identity()
    legacy['sync_original_names'] = {'proxmox': 'legacy-name'}
    legacy['operator_note'] = 'preserve me'
    legacy['sync_identities'].append({
        'schema': 'foreign',
        'opaque': 'preserve me too',
    })

    assert matches_vm_sync_identity(legacy, vm)
    vm.legacy_identity_owner = False
    assert not matches_vm_sync_identity(legacy, vm)
    vm.legacy_identity_owner = True

    migrated = build_vm_custom_fields(vm, legacy)
    assert vm_identity()['sync_identities'][0] in migrated['sync_identities']
    assert qemu_source_identity(vm).to_record() in migrated['sync_identities']
    assert {'schema': 'foreign', 'opaque': 'preserve me too'} in (
        migrated['sync_identities']
    )
    assert migrated['sync_original_names']['proxmox'] == 'legacy-name'
    assert migrated['sync_original_names']['proxmox/pve-infra-test/qemu'] == 'qemu-100'
    assert migrated['operator_note'] == 'preserve me'


def test_v2_match_beats_v1_but_same_rank_duplicates_remain_conflict():
    vm = _hosts()[0].virtual_machines[0]
    cluster = FakeRecord(id=3)
    legacy = _record(10, cluster, vm_identity())
    v2_fields = build_vm_custom_fields(vm)
    v2 = _record(11, cluster, v2_fields)

    assert find_vm_sync_identity_matches([legacy, v2], vm) == [v2]

    duplicate = _record(12, cluster, v2_fields)
    assert find_vm_sync_identity_matches([v2, duplicate], vm) == [v2, duplicate]


def test_node_migration_reuses_migrated_vm_and_disappearance_stays_clean(
        fake_netbox,
        capsys,
):
    _, _, cluster, target = add_target(fake_netbox)
    existing = fake_netbox.virtualization.virtual_machines.add(
        _record(
            10,
            cluster,
            {
                **vm_identity(),
                'operator_note': 'preserve me',
            },
            name='qemu-100',
        )
    )

    apply_virtual_machines(
        fake_netbox, _hosts('node-a'), target, confirmed=True,
    )
    assert qemu_source_identity(
        _hosts('node-a')[0].virtual_machines[0]
    ).to_record() in existing.custom_fields['sync_identities']

    fake_netbox.clear_mutations()
    migrated_hosts = _hosts('node-b')
    apply_virtual_machines(
        fake_netbox, migrated_hosts, target, confirmed=True,
    )

    assert fake_netbox.mutation_count('create') == 0
    assert fake_netbox.mutation_count('update') == 0
    assert existing.custom_fields['operator_note'] == 'preserve me'

    report_missing_managed_objects(fake_netbox, migrated_hosts, target)
    output = capsys.readouterr().out
    assert 'DISAPPEARANCE STATUS CLEAN' in output
    assert 'WARNING MISSING GUEST' not in output
    assert fake_netbox.mutation_count('delete') == 0


def test_non_owner_second_proxmox_source_cannot_claim_legacy_identity():
    legacy_fields = vm_identity()
    owner_vm = _hosts()[0].virtual_machines[0]
    second_config = replace(
        sample_source_config(), id='pve-second', source_instance='pve-second',
        legacy_identity_owner=False,
    )
    second_vm = discover_hosts(
        FakeProxmox(proxmox_responses()), second_config,
    )[0].virtual_machines[0]

    assert matches_vm_sync_identity(legacy_fields, owner_vm)
    assert not matches_vm_sync_identity(legacy_fields, second_vm)
