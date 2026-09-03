"""Contract checks for the external API test doubles."""

from tests.fakes import FakeRecord


def test_fake_proxmox_records_exact_request(fake_proxmox):
    fake_proxmox.responses[
        ('nodes', 'node-a', 'status')
    ] = {'status': 'ok'}

    result = fake_proxmox.nodes('node-a').status.get()

    assert result == {'status': 'ok'}
    assert fake_proxmox.calls == [
        (('nodes', 'node-a', 'status'), {}),
    ]


def test_fake_netbox_filters_and_records_mutations(fake_netbox):
    endpoint = fake_netbox.dcim.sites
    endpoint.add(
        FakeRecord(id=7, slug='test', name='Test')
    )

    assert endpoint.get(slug='test').id == 7

    created = endpoint.create(slug='new', name='New')
    created.update({'name': 'Changed'})

    assert fake_netbox.mutation_count('create') == 1
    assert fake_netbox.mutation_count('update') == 1
    assert created.name == 'Changed'
