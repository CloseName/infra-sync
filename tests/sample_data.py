"""Deterministic source fixtures shared by characterization tests."""

from proxmoxer import ResourceException

from netbox_sync.source_config import (
    NetBoxTargetConfig,
    SecretReference,
    SourceConfig,
    SourceCredentials,
)


def sample_source_config(address='pve.test.example'):
    """Return the explicit single source used by discovery tests."""

    return SourceConfig(
        id='pve-infra-test',
        source_instance='pve-infra-test',
        name='Test Proxmox',
        source_type='proxmox',
        address=address,
        enabled=True,
        sync_enabled=True,
        sync_interval_seconds=600,
        verify_ssl=False,
        target=NetBoxTargetConfig(
            site_slug='test-site',
            device_role_slug='server',
            platform_slug='proxmox',
            device_type_slug='generic',
            cluster_type_slug='proxmox',
            cluster_name='Test Cluster',
        ),
        credentials=SourceCredentials(
            username='sync@pve',
            token_id=SecretReference(
                provider='file',
                key='/run/secrets/proxmox_token_id',
            ),
            token_secret=SecretReference(
                provider='file',
                key='/run/secrets/proxmox_token_secret',
            ),
        ),
        legacy_identity_owner=True,
        settings={},
    )


def proxmox_responses(node_name='node-a', *, agent_available=True):
    """Build one host containing QEMU 100 and LXC 100."""

    agent_path = (
        'nodes',
        node_name,
        'qemu',
        100,
        'agent',
        'network-get-interfaces',
    )

    agent_response = {
        'result': [
            {
                'name': 'ens18',
                'hardware-address': 'AA:BB:CC:DD:EE:01',
                'ip-addresses': [
                    {
                        'ip-address': '10.20.30.40',
                        'prefix': 24,
                    },
                    {
                        'ip-address': '127.0.0.1',
                        'prefix': 8,
                    },
                    {
                        'ip-address': 'fe80::1',
                        'prefix': 64,
                    },
                ],
            },
        ],
    }

    if not agent_available:
        agent_response = ResourceException(
            500,
            'QEMU guest agent is not running',
            '',
        )

    return {
        ('cluster', 'status'): [
            {
                'type': 'node',
                'name': node_name,
                'ip': '10.20.30.10',
            },
        ],
        ('nodes',): [
            {
                'node': node_name,
                'status': 'online',
            },
        ],
        ('nodes', node_name, 'status'): {
            'cpuinfo': {
                'model': 'Example CPU',
                'vendor': 'GenuineIntel',
                'sockets': 1,
                'cores': 8,
                'cpus': 16,
            },
            'memory': {
                'total': 32 * 1024**3,
            },
            'pveversion': 'pve-manager/8.3.2/abc123',
        },
        ('nodes', node_name, 'disks', 'list'): [
            {
                'devpath': '/dev/sda',
                'model': 'Example SSD',
                'serial': 'DISK-001',
                'size': 512 * 1024**3,
                'type': 'ssd',
                'health': 'PASSED',
            },
        ],
        ('nodes', node_name, 'storage'): [
            {
                'storage': 'local-lvm',
                'type': 'lvmthin',
                'content': 'images,rootdir',
                'total': 400 * 1024**3,
                'used': 100 * 1024**3,
                'avail': 300 * 1024**3,
                'active': 1,
            },
        ],
        ('nodes', node_name, 'network'): [
            {
                'iface': 'vmbr0',
                'type': 'bridge',
                'active': 1,
                'autostart': 1,
                'method': 'static',
                'cidr': '10.20.30.10/24',
                'gateway': '10.20.30.1',
                'bridge_ports': 'eno1 eno2',
                'bridge_vlan_aware': 1,
                'comments': 'Management bridge',
            },
        ],
        ('nodes', node_name, 'qemu'): [
            {
                'vmid': 100,
                'name': 'qemu-100',
                'status': 'running',
            },
        ],
        ('nodes', node_name, 'qemu', 100, 'config'): {
            'sockets': 1,
            'cores': 4,
            'memory': 4096,
            'onboot': 1,
            'net0': (
                'virtio=AA:BB:CC:DD:EE:01,'
                'bridge=vmbr0,tag=120'
            ),
            'scsi0': 'local-lvm:vm-100-disk-0,size=32G',
            'ide2': 'none,media=cdrom',
        },
        agent_path: agent_response,
        ('nodes', node_name, 'lxc'): [
            {
                'vmid': 100,
                'name': 'lxc-100',
                'status': 'stopped',
            },
        ],
        ('nodes', node_name, 'lxc', 100, 'config'): {
            'hostname': 'lxc-100',
            'arch': 'amd64',
            'ostype': 'debian',
            'cores': 2,
            'memory': 2048,
            'swap': 512,
            'onboot': 0,
            'unprivileged': 1,
            'rootfs': 'local-lvm:subvol-100-disk-0,size=8G',
            'net0': (
                'name=eth0,bridge=vmbr0,'
                'hwaddr=AA:BB:CC:DD:EE:02,'
                'ip=10.20.30.50/24,tag=120'
            ),
        },
    }
