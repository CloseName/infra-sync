"""Characterize the current normalized Proxmox discovery output."""

from netbox_pve_sync.proxmox_discovery import discover_hosts

from tests.fakes import FakeProxmox
from tests.sample_data import (
    proxmox_responses,
    sample_source_config,
)


def test_discovers_host_qemu_lxc_storage_disks_and_networks():
    hosts = discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config(),
    )

    assert len(hosts) == 1
    host = hosts[0]

    assert host.source == 'proxmox'
    assert host.source_id == 'node-a'
    assert host.normalized_name == 'NODE-A'
    assert host.management_ip == '10.20.30.10'
    assert host.hypervisor_version == '8.3.2'
    assert host.cpu.cores == 8
    assert host.cpu.logical_cpus == 16
    assert host.memory_bytes == 32 * 1024**3

    assert len(host.disks) == 1
    assert host.disks[0].serial == 'DISK-001'
    assert host.disks[0].size_bytes == 512 * 1024**3
    assert len(host.storages) == 1
    assert host.storages[0].name == 'local-lvm'

    assert len(host.interfaces) == 1
    host_nic = host.interfaces[0]
    assert host_nic.name == 'vmbr0'
    assert host_nic.addresses == ['10.20.30.10/24']
    assert host_nic.bridge_ports == ['eno1', 'eno2']
    assert host_nic.vlan_aware is True

    assert len(host.virtual_machines) == 1
    vm = host.virtual_machines[0]
    assert vm.vmid == 100
    assert vm.source_id == 'proxmox:node-a:100'
    assert vm.vcpus == 4
    assert vm.memory_bytes == 4096 * 1024**2
    assert vm.autostart is True
    assert len(vm.disks) == 1
    assert vm.disks[0].name == 'scsi0'
    assert vm.disks[0].storage == 'local-lvm'
    assert vm.disks[0].size_bytes == 32 * 1024**3
    assert len(vm.interfaces) == 1
    assert vm.interfaces[0].mac_address == 'AA:BB:CC:DD:EE:01'
    assert vm.interfaces[0].vlan_id == 120
    assert vm.interfaces[0].ip_addresses == ['10.20.30.40/24']

    assert len(host.containers) == 1
    container = host.containers[0]
    assert container.vmid == 100
    assert container.source_id == 'proxmox:node-a:lxc:100'
    assert container.architecture == 'amd64'
    assert container.os_type == 'debian'
    assert container.unprivileged is True
    assert container.disks[0].size_bytes == 8 * 1024**3
    assert container.interfaces[0].name == 'eth0'
    assert container.interfaces[0].mac_address == 'AA:BB:CC:DD:EE:02'
    assert container.interfaces[0].ip_addresses == ['10.20.30.50/24']


def test_qemu_agent_unavailable_retains_nic_and_omits_ip_addresses():
    hosts = discover_hosts(
        FakeProxmox(
            proxmox_responses(agent_available=False)
        ),
        sample_source_config(),
    )

    vm = hosts[0].virtual_machines[0]

    assert len(vm.interfaces) == 1
    assert vm.interfaces[0].mac_address == 'AA:BB:CC:DD:EE:01'
    assert vm.interfaces[0].ip_addresses == []


def test_v1_identity_changes_after_live_migration_current_bug():
    before = discover_hosts(
        FakeProxmox(proxmox_responses('node-a')),
        sample_source_config(),
    )[0].virtual_machines[0]
    after = discover_hosts(
        FakeProxmox(proxmox_responses('node-b')),
        sample_source_config(),
    )[0].virtual_machines[0]

    # Characterization only: PHASE 2 must reverse this expectation.
    assert before.vmid == after.vmid == 100
    assert before.source_id == 'proxmox:node-a:100'
    assert after.source_id == 'proxmox:node-b:100'
    assert before.source_id != after.source_id
