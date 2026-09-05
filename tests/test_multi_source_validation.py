"""Final code-level heterogeneous source isolation matrix."""

from dataclasses import replace

from netbox_pve_sync.esxi_discovery import discover_hosts as discover_esxi
from netbox_pve_sync.orchestrator import run_sources
from netbox_pve_sync.proxmox_discovery import discover_hosts as discover_proxmox
from netbox_pve_sync.secret_resolver import FileSecretResolver
from netbox_pve_sync.source_config import SecretReference, SourceCredentials
from netbox_pve_sync.source_executor import SourceExecutorDispatch
from netbox_pve_sync.source_identity import (
    lxc_source_identity,
    qemu_source_identity,
    virtual_machine_source_identity,
)

from tests.fakes import FakeProxmox
from tests.fakes.esxi import fake_esxi_service
from tests.sample_data import proxmox_responses, sample_source_config
from tests.test_esxi import esxi_config


def _pve(instance='pve-a'):
    return replace(
        sample_source_config(), id=instance, source_instance=instance,
        legacy_identity_owner=False,
    )


def test_same_display_name_isolated_across_qemu_lxc_and_esxi():
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu')][0]['name'] = 'APP01'
    responses[('nodes', 'node-a', 'lxc', 100, 'config')]['hostname'] = 'APP01'
    pve_host = discover_proxmox(FakeProxmox(responses), _pve())[0]
    esxi_host = discover_esxi(
        fake_esxi_service(vm_name='APP01'), esxi_config('esxi-b'),
    )[0]
    qemu, lxc = pve_host.virtual_machines[0], pve_host.containers[0]
    esxi_vm = esxi_host.virtual_machines[0]

    identities = {
        qemu_source_identity(qemu), lxc_source_identity(lxc),
        virtual_machine_source_identity(esxi_vm),
    }

    assert qemu.original_name == lxc.original_name == esxi_vm.original_name == 'APP01'
    assert len(identities) == 3
    assert {identity.kind for identity in identities} == {'qemu', 'lxc', 'vm'}
    assert {identity.instance for identity in identities} == {'pve-a', 'esxi-b'}


def test_provider_dispatch_and_result_order_are_independent_of_input_order():
    calls = []
    dispatch = SourceExecutorDispatch({
        'proxmox': lambda config: calls.append(('proxmox', config.source_instance)),
        'esxi': lambda config: calls.append(('esxi', config.source_instance)),
    })
    sources = (_pve('pve-a'), esxi_config('esxi-b'))

    first = run_sources(tuple(reversed(sources)), dispatch.execute)
    first_calls = tuple(calls)
    calls.clear()
    second = run_sources(sources, dispatch.execute)

    assert first_calls == tuple(calls) == (('esxi', 'esxi-b'), ('proxmox', 'pve-a'))
    assert [item.source_instance for item in first.results] == [
        item.source_instance for item in second.results
    ] == ['esxi-b', 'pve-a']


def test_missing_secret_for_one_source_does_not_resolve_or_stop_other_source(tmp_path):
    (tmp_path / 'pve-b-token').write_text('token-b', encoding='utf-8')
    (tmp_path / 'pve-b-secret').write_text('secret-b', encoding='utf-8')
    resolver = FileSecretResolver(environ={}, secret_root=tmp_path)
    source_a = replace(_pve('pve-a'), credentials=SourceCredentials(
        'sync-a@pve', SecretReference('file', 'pve-a-token'),
        SecretReference('file', 'pve-a-secret'),
    ))
    source_b = replace(_pve('pve-b'), credentials=SourceCredentials(
        'sync-b@pve', SecretReference('file', 'pve-b-token'),
        SecretReference('file', 'pve-b-secret'),
    ))
    resolved = []

    def execute(config):
        credentials = resolver.resolve_credentials(config.credentials)
        resolved.append((config.source_instance, credentials.token_id))

    result = run_sources((source_b, source_a), execute)

    assert [item.success for item in result.results] == [False, True]
    assert resolved == [('pve-b', 'token-b')]
    assert result.results[0].error_summary == 'source execution failed'
    assert 'pve-a-token' not in repr(result)


def test_secret_resolver_observes_new_broker_file_without_restart(tmp_path):
    resolver = FileSecretResolver(environ={}, secret_root=tmp_path)
    reference = SecretReference('file', 'src-pve-prod-2-secret-abcdef12')

    (tmp_path / reference.key).write_text('new-secret', encoding='utf-8')

    assert resolver.resolve(reference) == 'new-secret'
