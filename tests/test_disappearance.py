"""Characterize retain-only disappearance reporting."""

from dataclasses import replace

from netbox_pve_sync.netbox_disappearance import (
    report_missing_managed_objects,
)
from netbox_pve_sync.netbox_planner import NetBoxTargetConfig
from netbox_pve_sync.proxmox_discovery import discover_hosts
from netbox_pve_sync.esxi_discovery import discover_hosts as discover_esxi_hosts

from tests.fakes import FakeProxmox, FakeRecord
from tests.sample_data import (
    proxmox_responses,
    sample_source_config,
)
from tests.fakes.esxi import fake_esxi_service
from tests.test_esxi import esxi_config


def test_disappearance_reports_missing_guest_without_delete(
        capsys,
        fake_netbox,
):
    site = fake_netbox.dcim.sites.add(
        FakeRecord(id=1, slug='test-site', name='Test Site')
    )
    cluster = fake_netbox.virtualization.clusters.add(
        FakeRecord(
            id=2,
            name='Test Cluster',
            scope_type='dcim.site',
            scope_id=site.id,
        )
    )
    fake_netbox.virtualization.virtual_machines.add(
        FakeRecord(
            id=3,
            name='missing-vm',
            cluster=cluster,
            custom_fields={
                'sync_identities': [
                    {
                        'source': 'proxmox',
                        'source_id': 'node-a:999',
                    },
                ],
            },
        )
    )

    hosts = discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config(),
    )
    config = NetBoxTargetConfig(
        site_slug='test-site',
        device_role_slug='server',
        platform_slug='proxmox',
        device_type_slug='generic',
        cluster_type_slug='proxmox',
        cluster_name='Test Cluster',
    )

    report_missing_managed_objects(
        fake_netbox,
        hosts,
        config,
    )

    output = capsys.readouterr().out
    assert 'WARNING MISSING GUEST' in output
    assert 'identity=proxmox:node-a:999' in output
    assert 'action=retained' in output
    assert 'No objects were deleted.' in output
    assert fake_netbox.mutation_count('delete') == 0
    assert fake_netbox.mutations == []


def test_disappearance_does_not_cross_source_instance_boundary(
        capsys,
        fake_netbox,
):
    site = fake_netbox.dcim.sites.add(
        FakeRecord(id=1, slug='test-site', name='Test Site')
    )
    cluster = fake_netbox.virtualization.clusters.add(
        FakeRecord(
            id=2,
            name='Test Cluster',
            scope_type='dcim.site',
            scope_id=site.id,
        )
    )
    for record_id, instance in ((3, 'pve-a'), (4, 'pve-b')):
        fake_netbox.virtualization.virtual_machines.add(
            FakeRecord(
                id=record_id,
                name=f'missing-{instance}',
                cluster=cluster,
                custom_fields={
                    'sync_identities': [{
                        'schema': 'v2',
                        'type': 'proxmox',
                        'instance': instance,
                        'kind': 'qemu',
                        'external_id': '999',
                    }],
                },
            )
        )

    source_config = replace(
        sample_source_config(),
        id='pve-a',
        source_instance='pve-a',
        legacy_identity_owner=False,
    )
    hosts = discover_hosts(
        FakeProxmox(proxmox_responses()),
        source_config,
    )

    report_missing_managed_objects(
        fake_netbox,
        hosts,
        source_config.target,
    )

    output = capsys.readouterr().out
    assert 'identity=proxmox/pve-a/qemu/999' in output
    assert 'pve-b' not in output
    assert fake_netbox.mutation_count('delete') == 0


def _add_esxi_target(fake_netbox):
    site = fake_netbox.dcim.sites.add(
        FakeRecord(id=1, slug='test-site', name='Test Site')
    )
    return fake_netbox.virtualization.clusters.add(
        FakeRecord(
            id=2,
            name='Test Cluster',
            scope_type='dcim.site',
            scope_id=site.id,
        )
    )


def _add_managed_vm(fake_netbox, cluster, record_id, source_type, instance, vm_id):
    fake_netbox.virtualization.virtual_machines.add(
        FakeRecord(
            id=record_id,
            name=f'vm-{record_id}',
            cluster=cluster,
            custom_fields={
                'sync_identities': [{
                    'schema': 'v2',
                    'type': source_type,
                    'instance': instance,
                    'kind': 'vm' if source_type == 'esxi' else 'qemu',
                    'external_id': vm_id,
                }],
            },
        )
    )


def test_esxi_disappearance_isolated_from_other_instance_and_proxmox(
        capsys,
        fake_netbox,
):
    cluster = _add_esxi_target(fake_netbox)
    _add_managed_vm(fake_netbox, cluster, 3, 'esxi', 'esxi-a', 'missing-a')
    _add_managed_vm(fake_netbox, cluster, 4, 'esxi', 'esxi-b', 'missing-b')
    _add_managed_vm(fake_netbox, cluster, 5, 'proxmox', 'pve-a', '999')
    config = esxi_config()
    hosts = discover_esxi_hosts(fake_esxi_service(), config)

    report_missing_managed_objects(fake_netbox, hosts, config.target)

    output = capsys.readouterr().out
    assert 'identity=esxi/esxi-a/vm/missing-a' in output
    assert 'esxi-b' not in output
    assert 'proxmox/pve-a' not in output
    assert fake_netbox.mutation_count('delete') == 0


def test_esxi_vm_rename_is_not_reported_missing(capsys, fake_netbox):
    cluster = _add_esxi_target(fake_netbox)
    stable_id = '503c5ad7-0000-1111-2222-0123456789ab'
    _add_managed_vm(fake_netbox, cluster, 3, 'esxi', 'esxi-a', stable_id)
    config = esxi_config()
    hosts = discover_esxi_hosts(
        fake_esxi_service(vm_name='RENAMED-VM'),
        config,
    )

    report_missing_managed_objects(fake_netbox, hosts, config.target)

    output = capsys.readouterr().out
    assert 'WARNING MISSING GUEST' not in output
    assert fake_netbox.mutation_count('delete') == 0
