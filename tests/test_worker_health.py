"""Health operation is bounded and cannot invoke privileged worker behavior."""

import json

import pytest

from netbox_pve_sync.api.worker_health import WorkerHealthClient
from netbox_pve_sync.apply_worker import ApplyWorkerError
from netbox_pve_sync.apply_worker import _handle_request as apply_handle
from netbox_pve_sync.apply_worker import _receive as apply_receive
from netbox_pve_sync.discovery_worker import WorkerError
from netbox_pve_sync.discovery_worker import _handle_request as discovery_handle
from netbox_pve_sync.discovery_worker import _receive as discovery_receive


class ReceiveConnection:
    def __init__(self, payload):
        self.payload = payload

    def settimeout(self, _timeout):
        pass

    def recv(self, _size):
        payload, self.payload = self.payload, b''
        return payload


class Socket:
    def __init__(self, response=None, failure=None):
        self.response = response
        self.failure = failure
        self.sent = None
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, _path):
        if self.failure:
            raise self.failure

    def sendall(self, value):
        self.sent = value

    def shutdown(self, _direction):
        pass

    def recv(self, _size):
        return self.response


def test_workers_accept_only_empty_health_operation_without_source():
    payload = b'{"operation":"health"}'
    assert discovery_receive(ReceiveConnection(payload)) == (None, 'health')
    assert apply_receive(ReceiveConnection(payload)) == {'operation': 'health'}


def test_workers_reject_health_operation_with_any_extra_field():
    payload = b'{"operation":"health","source_instance":"pve-test"}'
    with pytest.raises(WorkerError, match='REQUEST_INVALID'):
        discovery_receive(ReceiveConnection(payload))
    with pytest.raises(ApplyWorkerError, match='REQUEST_INVALID'):
        apply_receive(ReceiveConnection(payload))


def test_worker_health_never_calls_supervisor_operations():
    class ForbiddenSupervisor:
        def __getattr__(self, _name):
            raise AssertionError('health must not touch the supervisor')
    supervisor = ForbiddenSupervisor()
    assert discovery_handle(supervisor, None, 'health') == {'status': 'ok'}
    assert apply_handle(supervisor, {'operation': 'health'}) == {'status': 'ok'}


def test_worker_health_client_accepts_only_exact_response_and_short_timeout():
    connection = Socket(json.dumps({'ok': True, 'result': {'status': 'ok'}}).encode())
    client = WorkerHealthClient('/worker.sock', connector=lambda *_args: connection)
    assert client.health() is True
    assert connection.sent == b'{"operation":"health"}'
    assert connection.timeout == 1.0
    for response in (b'{}', b'{"ok":true,"result":{"status":"ok","secret":"x"}}', b'bad'):
        assert WorkerHealthClient('/worker.sock', connector=lambda *_args, value=response:
                                  Socket(value)).health() is False


def test_worker_health_socket_failure_is_safe_and_empty_socket_is_unavailable():
    client = WorkerHealthClient('/worker.sock', connector=lambda *_args:
                                Socket(failure=OSError('RAW_SOCKET_SECRET')))
    assert client.health() is False
    timeout = WorkerHealthClient('/worker.sock', connector=lambda *_args:
                                 Socket(failure=TimeoutError('RAW_TIMEOUT_SECRET')))
    assert timeout.health() is False
    assert WorkerHealthClient('').health() is False
