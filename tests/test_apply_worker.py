"""WEB-5 apply worker rejects capability-bearing input and sanitizes children."""

import json
import subprocess

import pytest

from netbox_pve_sync.apply_worker import ApplySupervisor, ApplyWorkerError, _receive
from netbox_pve_sync.discovery_worker import _safe_environment


class Connection:
    """One-shot local socket fixture."""

    def __init__(self, value):
        self.value = value

    def settimeout(self, _value):
        """Accept the worker's bounded-read timeout."""

    def recv(self, _size):
        value, self.value = self.value, b''
        return value


def test_worker_accepts_only_fixed_well_formed_prepare_and_apply_requests():
    """Digest/token shape is validated before privileged work."""
    prepare = {'operation': 'prepare', 'source_instance': 'pve-test',
               'plan_digest': 'a' * 64}
    apply = {'operation': 'apply', 'source_instance': 'pve-test',
             'confirmation_token': 'b' * 64}
    assert _receive(Connection(json.dumps(prepare).encode())) == prepare
    assert _receive(Connection(json.dumps(apply).encode())) == apply


@pytest.mark.parametrize('payload', [
    {'operation': 'apply', 'source_instance': 'pve-test', 'confirmation_token': 'x',
     'command': 'docker'},
    {'operation': 'apply', 'source_instance': 'pve-test', 'confirmation_token': 'x',
     'operations': ['delete']},
    {'operation': 'prepare', 'source_instance': 'pve-test', 'plan_digest': 'x',
     'secret_path': '/etc/shadow'},
])
def test_worker_protocol_rejects_commands_operations_and_paths(payload):
    with pytest.raises(ApplyWorkerError, match='REQUEST_INVALID'):
        _receive(Connection(json.dumps(payload).encode()))


def test_apply_child_environment_has_no_registration_or_registry_writer_credentials(monkeypatch):
    monkeypatch.setenv('INFRA_SYNC_REGISTRATION_DSN', 'registration-secret')
    monkeypatch.setenv('INFRA_SYNC_APPLY_REGISTRY_DSN', 'reader-secret')
    monkeypatch.setenv('NB_APPLY_API_TOKEN', 'apply-secret')
    environment = _safe_environment()
    assert 'INFRA_SYNC_REGISTRATION_DSN' not in environment
    assert 'INFRA_SYNC_APPLY_REGISTRY_DSN' not in environment
    assert 'NB_APPLY_API_TOKEN' not in environment


class TimedOutProcess:
    """Popen-shaped timeout fixture."""

    returncode = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def communicate(self, _payload=None, timeout=None):
        if timeout is not None:
            raise subprocess.TimeoutExpired('child', timeout)
        return b'', b''

    def kill(self):
        self.returncode = -9


@pytest.mark.parametrize(('operation', 'code'), [
    ('plan', 'FAILED_BEFORE_WRITE'), ('apply', 'OUTCOME_UNCERTAIN'),
])
def test_timeout_distinguishes_prewrite_from_uncertain_apply(operation, code):
    """A timed-out write is never retried or misreported as safely failed."""
    supervisor = ApplySupervisor('', '', '', '', '', '', '', popen=lambda *_args, **_kwargs:
                                 TimedOutProcess())
    with pytest.raises(ApplyWorkerError, match=code):
        supervisor._child({'operation': operation})  # pylint: disable=protected-access
