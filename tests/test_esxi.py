"""Standalone ESXi adapter, discovery, identity, and executor tests."""

from dataclasses import replace

import pytest

from netbox_pve_sync.esxi_client import (
    EsxiClient,
    EsxiConnectionError,
    test_source_connection as check_source_connection,
)
from netbox_pve_sync.esxi_discovery import discover_hosts
from netbox_pve_sync.esxi_executor import execute_esxi_source
from netbox_pve_sync.orchestrator import run_sources
from netbox_pve_sync.source_config import SecretReference, SourceCredentials
from netbox_pve_sync.source_executor import SourceExecutorDispatch
from netbox_pve_sync.source_identity import (
    host_source_identity,
    virtual_machine_nic_source_identity,
    virtual_machine_source_identity,
)

from tests.fakes.esxi import fake_esxi_service, ns
from tests.sample_data import sample_source_config


class FakeResolver:
    """Secret resolver returning an injected ephemeral value."""

    def __init__(self, value='fake-password'):
        self.value = value
        self.references = []

    def resolve(self, reference):
        self.references.append(reference)
        return self.value


def esxi_config(source_id='esxi-a', password_key='ESXI_A_PASSWORD'):
    """Return one valid password-reference-only ESXi SourceConfig."""

    password = SecretReference(provider='env', key=password_key)
    return replace(
        sample_source_config(address=f'{source_id}.example.test'),
        id=source_id,
        source_instance=source_id,
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=SourceCredentials.for_password('root', password),
    )


def test_esxi_host_vm_datastore_disk_nic_and_tools_ip_mapping():
    host = discover_hosts(fake_esxi_service(), esxi_config())[0]
    vm = host.virtual_machines[0]

    assert host.source == 'esxi'
    assert host.source_instance == 'esxi-a'
    assert host.source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'
    assert host.management_ip == '192.0.2.10'
    assert host.hypervisor == 'VMware ESXi'
    assert host.hypervisor_version == '8.0.3 build-24022510'
    assert (host.cpu.sockets, host.cpu.cores, host.cpu.logical_cpus) == (2, 16, 32)
    assert host.memory_bytes == 128 * 1024**3
    assert host.interfaces[0].name == 'vmnic0'
    assert host.disks[0].serial == 'FAKE-SERIAL'
    assert host.storages[0].name == 'datastore1'
    assert host.storages[0].used_bytes == 300 * 1024**3
    assert vm.status == 'running'
    assert vm.vcpus == 4
    assert vm.memory_bytes == 8192 * 1024**2
    assert vm.autostart is True
    assert vm.disks[0].storage == 'datastore1'
    assert vm.interfaces[0].external_id == '4000'
    assert vm.interfaces[0].vlan_id == 120
    assert vm.interfaces[0].ip_addresses == ['192.0.2.50/24']


def _esxi_67_inventory(host, vm_folder_children=()):
    compute_resource = ns(
        _moId='ha-compute-res',
        name=host.name,
        host=[host],
    )
    host_folder = ns(
        _moId='ha-folder-host',
        name='host',
        childEntity=[compute_resource],
    )
    vm_folder = ns(
        _moId='ha-folder-vm',
        name='vm',
        childEntity=list(vm_folder_children),
    )
    datacenter = ns(
        _moId='ha-datacenter',
        name='ha-datacenter',
        hostFolder=host_folder,
        vmFolder=vm_folder,
    )
    root = ns(
        _moId='ha-folder-root',
        name='root',
        childEntity=[datacenter],
    )
    return ns(RetrieveContent=lambda: ns(rootFolder=root))


def test_standalone_esxi_67_host_folder_inventory_is_discovered():
    host = fake_esxi_service().host

    discovered = discover_hosts(_esxi_67_inventory(host), esxi_config())

    assert len(discovered) == 1
    assert discovered[0].original_name == 'esxi-a.example.test'
    assert discovered[0].source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'


def test_vm_folder_objects_are_not_interpreted_as_hosts():
    host = fake_esxi_service().host
    decoy = fake_esxi_service().host
    decoy.name = 'vm-folder-decoy.example.test'
    decoy.hardware.systemInfo.uuid = 'vm-folder-decoy-uuid'

    discovered = discover_hosts(
        _esxi_67_inventory(host, vm_folder_children=[decoy]),
        esxi_config(),
    )

    assert [item.source_id for item in discovered] == [
        '420f37d2-7a3b-4c1d-8e9f-001122334455'
    ]


def test_valid_esxi_host_hardware_uuid_is_used():
    discovered = discover_hosts(fake_esxi_service(), esxi_config())[0]

    assert discovered.source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'


@pytest.mark.parametrize(
    'hardware_uuid',
    (
        '',
        '00000000-0000-0000-0000-000000000000',
        '00000000-0000-0000-0000-ac1f6b021cb0',
        'not-a-uuid',
    ),
)
def test_unusable_esxi_host_hardware_uuid_falls_back_to_managed_id(
        hardware_uuid,
):
    service = fake_esxi_service()
    service.host.hardware.systemInfo.uuid = hardware_uuid
    service.host._moId = 'ha-host'

    discovered = discover_hosts(service, esxi_config())[0]

    assert discovered.source_id == 'ha-host'


def test_same_managed_host_id_is_isolated_by_source_instance():
    first_service = fake_esxi_service()
    second_service = fake_esxi_service()
    for service in (first_service, second_service):
        service.host.hardware.systemInfo.uuid = (
            '00000000-0000-0000-0000-ac1f6b021cb0'
        )
        service.host._moId = 'ha-host'

    first = discover_hosts(first_service, esxi_config('esxi-a'))[0]
    second = discover_hosts(second_service, esxi_config('esxi-b'))[0]

    assert first.source_id == second.source_id == 'ha-host'
    assert host_source_identity(first) != host_source_identity(second)


def test_host_uuid_validation_does_not_change_vm_identity():
    service = fake_esxi_service()
    service.host.hardware.systemInfo.uuid = (
        '00000000-0000-0000-0000-ac1f6b021cb0'
    )
    service.host._moId = 'ha-host'

    discovered = discover_hosts(service, esxi_config())[0]

    assert discovered.virtual_machines[0].external_id == (
        '503c5ad7-0000-1111-2222-0123456789ab'
    )


@pytest.mark.parametrize(
    ('power_state', 'expected'),
    (('poweredOn', 'running'), ('poweredOff', 'stopped'), ('suspended', 'stopped')),
)
def test_esxi_power_state_mapping(power_state, expected):
    host = discover_hosts(
        fake_esxi_service(power_state=power_state),
        esxi_config(),
    )[0]

    assert host.virtual_machines[0].status == expected


def test_missing_vmware_tools_and_optional_hardware_are_safe():
    host = discover_hosts(
        fake_esxi_service(
            tools_available=False,
            optional_hardware=False,
        ),
        esxi_config(),
    )[0]

    assert host.cpu.model is None
    assert host.cpu.sockets == 0
    assert host.virtual_machines[0].interfaces[0].ip_addresses == []


def test_vm_rename_preserves_uuid_and_nic_identity():
    before = discover_hosts(fake_esxi_service(vm_name='OLD'), esxi_config())[0]
    after = discover_hosts(fake_esxi_service(vm_name='NEW'), esxi_config())[0]
    before_vm = before.virtual_machines[0]
    after_vm = after.virtual_machines[0]

    assert before_vm.original_name != after_vm.original_name
    assert before_vm.external_id == '503c5ad7-0000-1111-2222-0123456789ab'
    assert virtual_machine_source_identity(before_vm) == (
        virtual_machine_source_identity(after_vm)
    )
    assert virtual_machine_source_identity(before_vm).kind == 'vm'
    assert virtual_machine_nic_source_identity(
        before_vm, before_vm.interfaces[0],
    ) == virtual_machine_nic_source_identity(
        after_vm, after_vm.interfaces[0],
    )
    assert virtual_machine_nic_source_identity(
        before_vm, before_vm.interfaces[0],
    ).kind == 'vm-nic'


def test_same_vm_uuid_is_isolated_by_source_instance():
    first = discover_hosts(fake_esxi_service(), esxi_config('esxi-a'))[0]
    second = discover_hosts(fake_esxi_service(), esxi_config('esxi-b'))[0]
    first_vm = first.virtual_machines[0]
    second_vm = second.virtual_machines[0]

    assert first_vm.external_id == second_vm.external_id
    assert virtual_machine_source_identity(first_vm) != (
        virtual_machine_source_identity(second_vm)
    )
    assert virtual_machine_nic_source_identity(
        first_vm, first_vm.interfaces[0],
    ) != virtual_machine_nic_source_identity(
        second_vm, second_vm.interfaces[0],
    )


@pytest.mark.parametrize('verify_ssl', (True, False))
def test_esxi_client_honors_tls_flag_and_disconnects(verify_ssl):
    connected = []
    disconnected = []
    service = fake_esxi_service()
    config = replace(esxi_config(), verify_ssl=verify_ssl)
    client = EsxiClient(
        resolver=FakeResolver(),
        connector=lambda host, user, password, verify: connected.append(
            (host, user, password, verify)
        ) or service,
        disconnecter=disconnected.append,
    )

    with client.session(config) as session:
        assert session is service

    assert connected == [(
        config.address, 'root', 'fake-password', verify_ssl,
    )]
    assert disconnected == [service]


def test_esxi_connection_test_reports_success_and_disconnects():
    service = fake_esxi_service()
    disconnected = []
    client = EsxiClient(
        resolver=FakeResolver(),
        connector=lambda *_args: service,
        disconnecter=disconnected.append,
    )

    result = check_source_connection(esxi_config(), client=client)

    assert result.success is True
    assert result.summary == 'ESXi connection test succeeded'
    assert disconnected == [service]


def test_authentication_failure_is_safe_and_contains_no_password():
    secret = 'FAKE_ESXI_PASSWORD_MUST_NOT_APPEAR'
    client = EsxiClient(
        resolver=FakeResolver(secret),
        connector=lambda *_args: (_ for _ in ()).throw(
            RuntimeError(f'authentication failed for {secret}')
        ),
    )

    with pytest.raises(EsxiConnectionError) as error:
        with client.session(esxi_config()):
            pass

    assert secret not in repr(error.value)
    result = check_source_connection(esxi_config(), client=client)
    assert result.success is False
    assert secret not in repr(result)


def test_esxi_executor_dispatches_discovery_to_shared_reconciliation():
    service = fake_esxi_service()
    client = EsxiClient(
        resolver=FakeResolver(),
        connector=lambda *_args: service,
        disconnecter=lambda _service: None,
    )
    seen = []

    execute_esxi_source(
        esxi_config(),
        'plan',
        lambda config, hosts, mode: seen.append((config, hosts, mode)),
        client=client,
    )

    assert seen[0][0].source_type == 'esxi'
    assert seen[0][1][0].source == 'esxi'
    assert seen[0][2] == 'plan'


@pytest.mark.parametrize('failing_type', ('esxi', 'proxmox'))
def test_mixed_source_failure_isolation(failing_type):
    calls = []
    configs = (
        esxi_config(),
        replace(
            sample_source_config(),
            id='pve-a',
            source_instance='pve-a',
            legacy_identity_owner=False,
        ),
    )

    def executor(config):
        calls.append(config.id)
        if config.source_type == failing_type:
            raise RuntimeError('safe fake failure')

    dispatch = SourceExecutorDispatch({
        'esxi': executor,
        'proxmox': executor,
    })
    result = run_sources(configs, dispatch.execute)

    assert calls == ['esxi-a', 'pve-a']
    assert result.succeeded == 1
    assert result.failed == 1
