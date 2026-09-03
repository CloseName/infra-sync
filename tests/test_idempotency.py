"""Characterize idempotent QEMU create and update behavior."""

from copy import deepcopy

from netbox_pve_sync.netbox_vm_apply import apply_virtual_machines
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
