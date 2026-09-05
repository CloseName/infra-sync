"""Narrow schedule control protocol and API tests."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netbox_pve_sync.api.app import create_app
from netbox_pve_sync.api.schedule_client import ScheduleRequestError
from netbox_pve_sync.api.settings import ApiSettings
from netbox_pve_sync.application.schedules import ScheduleView
from netbox_pve_sync.application.schedules import ScheduleReadError
from netbox_pve_sync.schedule_worker import ScheduleWorkerError, _authorize, _handle, _receive


class Connection:
    def __init__(self, value): self.value = value
    def settimeout(self, _timeout): pass
    def recv(self, _size):
        value, self.value = self.value, b''
        return value


class Store:
    def __init__(self): self.requests = []
    def update(self, request): self.requests.append(request); return {'source_instance': 'pve-test'}


def request(**changes):
    value = dict(operation='update_schedule', source_instance='pve-test', sync_enabled=True,
                 sync_interval_seconds=600, expected_sync_enabled=False,
                 expected_sync_interval_seconds=600)
    value.update(changes)
    return json.dumps(value).encode()


def test_protocol_accepts_only_health_or_exact_schedule_fields():
    assert _receive(Connection(b'{"operation":"health"}')) == {'operation': 'health'}
    assert _receive(Connection(request()))['sync_interval_seconds'] == 600
    for payload in (request(enabled=True), request(sync_interval_seconds=59),
                    request(operation='sql'), request(source_instance='INVALID')):
        with pytest.raises(ScheduleWorkerError, match='SCHEDULE_INVALID'):
            _receive(Connection(payload))


def test_health_does_not_touch_store_and_update_is_narrow():
    store = Store()
    assert _handle(store, {'operation': 'health'}) == {'status': 'ok'}
    parsed = _receive(Connection(request()))
    _handle(store, parsed)
    assert set(store.requests[0]) == {'operation', 'source_instance', 'sync_enabled',
                                     'sync_interval_seconds', 'expected_sync_enabled',
                                     'expected_sync_interval_seconds'}


def test_schedule_worker_preserves_peer_authentication(monkeypatch):
    monkeypatch.setattr('netbox_pve_sync.schedule_worker.socket.SO_PEERCRED', 17, raising=False)
    peer = SimpleNamespace(getsockopt=lambda *_args: __import__('struct').pack('3i', 1, 10002, 1))
    with pytest.raises(ScheduleWorkerError, match='PEER_FORBIDDEN'):
        _authorize(peer, 10001)


class ScheduleService:
    def __init__(self): self.values = []
    def get(self, instance): return view(instance)
    def update(self, instance, values): self.values.append((instance, values)); return view(instance, True, 300)


def view(instance='pve-test', enabled=False, interval=600):
    return ScheduleView(instance, enabled, interval, 'DUE', None,
                        datetime(2026, 9, 5, tzinfo=timezone.utc))


def headers():
    return {'Origin': 'http://testserver', 'X-Infra-Sync-CSRF': 'same-origin',
            'Content-Type': 'application/json'}


def test_schedule_read_and_protected_optimistic_update():
    service = ScheduleService()
    settings = ApiSettings(allowed_write_hosts=('testserver',))
    with TestClient(create_app(settings, schedule_service=service)) as client:
        read = client.get('/api/v1/sources/pve-test/schedule')
        updated = client.patch('/api/v1/sources/pve-test/schedule', headers=headers(), json={
            'sync_enabled': True, 'sync_interval_seconds': 300,
            'expected_sync_enabled': False, 'expected_sync_interval_seconds': 600})
    assert read.status_code == 200 and read.json()['scheduler_state'] == 'DUE'
    assert updated.status_code == 200 and updated.json()['sync_enabled'] is True
    assert service.values[0][1]['expected_sync_enabled'] is False


@pytest.mark.parametrize('interval', [0, 59, 86401, '600', True])
def test_schedule_api_rejects_invalid_intervals(interval):
    settings = ApiSettings(allowed_write_hosts=('testserver',))
    with TestClient(create_app(settings, schedule_service=ScheduleService())) as client:
        response = client.patch('/api/v1/sources/pve-test/schedule', headers=headers(), json={
            'sync_enabled': True, 'sync_interval_seconds': interval,
            'expected_sync_enabled': False, 'expected_sync_interval_seconds': 600})
    assert response.status_code == 422


@pytest.mark.parametrize(('code', 'status'), [('SCHEDULE_CONFLICT', 409),
                                               ('SOURCE_NOT_FOUND', 404),
                                               ('CONTROL_WORKER_UNAVAILABLE', 503)])
def test_schedule_errors_are_safe(code, status):
    class Failing(ScheduleService):
        def update(self, _instance, _values): raise ScheduleRequestError(code)
    settings = ApiSettings(allowed_write_hosts=('testserver',))
    with TestClient(create_app(settings, schedule_service=Failing())) as client:
        response = client.patch('/api/v1/sources/pve-test/schedule', headers=headers(), json={
            'sync_enabled': True, 'sync_interval_seconds': 600,
            'expected_sync_enabled': False, 'expected_sync_interval_seconds': 600})
    assert response.status_code == status and response.json()['error']['code'] == code
    assert 'dsn' not in response.text.casefold()


def test_schedule_read_failure_is_safe_and_api_has_no_writer_dsn():
    class Failing(ScheduleService):
        def get(self, _instance): raise ScheduleReadError()
    with TestClient(create_app(ApiSettings(), schedule_service=Failing())) as client:
        response = client.get('/api/v1/sources/pve-test/schedule')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'SCHEDULE_UNAVAILABLE'
    compose = __import__('pathlib').Path('compose.web.yml').read_text(encoding='utf-8')
    api = compose.split('  infra-sync-secret-broker:', 1)[0]
    assert 'INFRA_SYNC_SCHEDULE_WRITER_DSN' not in api
    assert 'docker.sock' not in compose and 'systemctl' not in compose
