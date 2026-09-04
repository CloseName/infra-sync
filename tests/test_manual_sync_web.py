"""WEB-5 HTTP boundary accepts only exact-plan capabilities."""

from fastapi.testclient import TestClient

from netbox_pve_sync.api.app import create_app
from netbox_pve_sync.api.settings import ApiSettings


HEADERS = {'host': 'localhost:8000', 'origin': 'http://localhost:8000',
           'x-infra-sync-csrf': 'same-origin', 'content-type': 'application/json'}


class Discovery:
    def plan(self, instance):
        return {'source_instance': instance, 'source_id': 'internal', 'source_type': 'proxmox',
                'source_fingerprint': 'a', 'target_fingerprint': 'b',
                'provider_fingerprint': 'c', 'netbox_fingerprint': 'd', 'schema_version': 1,
                'planner_version': 'web-5a-1', 'items': [], 'apply_allowed': True,
                'digest': 'a' * 64}

    def discover(self, _instance):
        raise AssertionError('discovery endpoint not used')


class Apply:
    def __init__(self):
        self.calls = []

    def prepare(self, instance, digest):
        self.calls.append(('prepare', instance, digest))
        return {'confirmation_token': 'b' * 64, 'expires_in_seconds': 300}

    def apply(self, instance, token):
        self.calls.append(('apply', instance, token))
        return {'status': 'SUCCEEDED', 'plan_digest': 'a' * 64}


def test_plan_prepare_apply_flow_and_payload_boundaries():
    worker = Apply()
    api = TestClient(create_app(ApiSettings(allowed_write_hosts=('localhost:8000',)),
                                discovery_client=Discovery(), apply_client=worker))
    planned = api.post('/api/v1/sources/pve-test/sync-plan', headers=HEADERS, json={})
    assert planned.status_code == 200
    assert 'source_id' not in planned.json()
    prepared = api.post('/api/v1/sources/pve-test/sync-confirmations', headers=HEADERS,
                        json={'plan_digest': 'a' * 64, 'confirmed': True})
    assert prepared.status_code == 200
    applied = api.post('/api/v1/sources/pve-test/sync', headers=HEADERS,
                       json={'confirmation_token': 'b' * 64})
    assert applied.status_code == 200
    assert worker.calls == [('prepare', 'pve-test', 'a' * 64),
                            ('apply', 'pve-test', 'b' * 64)]


def test_client_cannot_submit_operations_or_skip_same_origin_boundary():
    worker = Apply()
    api = TestClient(create_app(ApiSettings(allowed_write_hosts=('localhost:8000',)),
                                discovery_client=Discovery(), apply_client=worker))
    assert api.post('/api/v1/sources/pve-test/sync-plan', headers=HEADERS,
                    json={'operations': ['delete']}).status_code == 422
    response = api.post('/api/v1/sources/pve-test/sync', headers=HEADERS,
                        json={'confirmation_token': 'b' * 64, 'operations': ['delete']})
    assert response.status_code == 422
    assert worker.calls == []
    assert api.post('/api/v1/sources/pve-test/sync',
                    json={'confirmation_token': 'b' * 64}).status_code == 403
