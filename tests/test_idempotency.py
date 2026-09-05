"""Characterize idempotent QEMU create and update behavior."""

from copy import deepcopy

from netbox_pve_sync.netbox_vm_apply import apply_virtual_machines
from netbox_pve_sync.netbox_lxc_apply import apply_lxc_containers
from netbox_pve_sync.proxmox_discovery import discover_hosts

from tests.fakes import FakeProxmox, FakeRecord
from tests.netbox_scenarios import add_target, vm_identity
from tests.sample_data import (
    proxmox_responses,
    sample_source_config,
)


def test_second_vm_apply_has_zero_create_and_update(fake_netbox):
    _, _, cluster, config = add_target(fake_netbox)
    hosts = discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config(),
    )
    original = hosts[0].virtual_machines[0]
    additional = deepcopy(original)
    additional.vmid = 101
    additional.source_id = 'proxmox:node-a:101'
    additional.original_name = 'qemu-101'
    additional.normalized_name = 'qemu-101'
    hosts[0].virtual_machines.append(additional)

    existing = fake_netbox.virtualization.virtual_machines.add(
        FakeRecord(
            id=10,
            name='old-qemu-name',
            cluster=cluster,
            tenant=None,
            status='offline',
            vcpus=1,
            memory=512,
            disk=1024,
            start_on_boot='off',
            custom_fields={
                **vm_identity(),
                'operator_note': 'preserve me',
            },
        )
    )

    apply_virtual_machines(
        fake_netbox,
        hosts,
        config,
        confirmed=True,
    )

    assert fake_netbox.mutation_count('create') == 1
    assert fake_netbox.mutation_count('update') == 1
    assert existing.name == 'qemu-100'
    assert existing.custom_fields['operator_note'] == 'preserve me'
    assert len(
        fake_netbox.virtualization.virtual_machines.all()
    ) == 2

    fake_netbox.clear_mutations()

    apply_virtual_machines(
        fake_netbox,
        hosts,
        config,
        confirmed=True,
    )

    assert fake_netbox.mutation_count('create') == 0
    assert fake_netbox.mutation_count('update') == 0
    assert fake_netbox.mutations == []


def test_qemu_rename_updates_same_object_then_is_idempotent(fake_netbox):
    _, _, _, config = add_target(fake_netbox)
    before = discover_hosts(
        FakeProxmox(proxmox_responses()), sample_source_config(),
    )
    apply_virtual_machines(fake_netbox, before, config, confirmed=True)
    record = fake_netbox.virtualization.virtual_machines.all()[0]
    record_id = record.id

    after_responses = proxmox_responses()
    after_responses[('nodes', 'node-a', 'qemu')][0]['name'] = 'renamed-qemu'
    after = discover_hosts(
        FakeProxmox(after_responses), sample_source_config(),
    )
    fake_netbox.clear_mutations()
    apply_virtual_machines(fake_netbox, after, config, confirmed=True)

    assert fake_netbox.mutation_count('create') == 0
    assert fake_netbox.mutation_count('update') == 1
    assert record.id == record_id
    assert record.name == 'renamed-qemu'
    identity = deepcopy(record.custom_fields['sync_identities'])

    fake_netbox.clear_mutations()
    apply_virtual_machines(fake_netbox, after, config, confirmed=True)
    assert fake_netbox.mutations == []
    assert record.custom_fields['sync_identities'] == identity


def test_lxc_rename_updates_same_object_then_is_idempotent(fake_netbox):
    _, _, _, config = add_target(fake_netbox)
    before = discover_hosts(
        FakeProxmox(proxmox_responses()), sample_source_config(),
    )
    apply_lxc_containers(fake_netbox, before, config, confirmed=True)
    record = fake_netbox.virtualization.virtual_machines.all()[0]
    # A subsequent real NetBox read returns the cluster relationship object.
    record.cluster = fake_netbox.virtualization.clusters.all()[0]
    record_id = record.id

    after_responses = proxmox_responses()
    after_responses[('nodes', 'node-a', 'lxc', 100, 'config')]['hostname'] = (
        'renamed-lxc'
    )
    after = discover_hosts(
        FakeProxmox(after_responses), sample_source_config(),
    )
    fake_netbox.clear_mutations()
    apply_lxc_containers(fake_netbox, after, config, confirmed=True)

    assert fake_netbox.mutation_count('create') == 0
    assert fake_netbox.mutation_count('update') == 1
    assert record.id == record_id
    assert record.name == 'renamed-lxc'
    identity = deepcopy(record.custom_fields['sync_identities'])

    fake_netbox.clear_mutations()
    apply_lxc_containers(fake_netbox, after, config, confirmed=True)
    assert fake_netbox.mutations == []
    assert record.custom_fields['sync_identities'] == identity
