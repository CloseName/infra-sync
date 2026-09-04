"""Dedicated Unix-socket supervisor for confirmed one-source manual sync."""
# pylint: disable=import-outside-toplevel,too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-instance-attributes,subprocess-popen-preexec-fn,no-member
# pylint: disable=line-too-long,missing-class-docstring,missing-function-docstring
# pylint: disable=too-few-public-methods,import-error,duplicate-code

import argparse
import json
import os
import re
import socket
import subprocess
import struct
import sys
from dataclasses import asdict
from pathlib import Path

import psycopg

from .application.confirmation import ConfirmationClaims, ConfirmationError, ConfirmationStore
from .discovery_worker import (_bounded_secret, _child_config, _config_payload, _drop_privileges,
                               _safe_environment)
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_registry import SourceRegistry

MAX_REQUEST = 4096
MAX_RESPONSE = 8 * 1024 * 1024
CHILD_TIMEOUT = 300
DIGEST_PATTERN = re.compile(r'^[a-f0-9]{64}$')
TOKEN_PATTERN = re.compile(r'^[a-f0-9]{64}$')


class ApplyWorkerError(RuntimeError):
    """Stable, secret-free worker failure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _discover(payload):
    """Build provider inventory inside the unprivileged child."""
    from proxmoxer import ProxmoxAPI
    from .esxi_client import EsxiClient
    from .esxi_discovery import discover_hosts as discover_esxi
    from .proxmox_discovery import discover_hosts as discover_proxmox
    source = dict(payload['source'])
    credentials = payload['credentials']
    source['username'] = credentials['username']
    config = _child_config(source)
    if config.source_type == 'proxmox':
        provider = ProxmoxAPI(
            config.address, user=credentials['username'],
            token_name=credentials['token_id'].split('!', 1)[-1],
            token_value=credentials['token_secret'], verify_ssl=config.verify_ssl)
        return config, discover_proxmox(provider, config)
    if config.source_type == 'esxi':
        class Resolved:
            def resolve(self, _reference):
                return credentials['token_secret']
        with EsxiClient(resolver=Resolved()).session(config) as service:
            return config, discover_esxi(service, config)
    raise ApplyWorkerError('SOURCE_UNSUPPORTED')


def _plan(nb_api, hosts, config):
    from .application.discovery_review import build_esxi_review, build_proxmox_review
    from .application.planning_netbox import PlanningNetBox
    from .application.sync_plan import plan_from_mutations, plan_from_review
    from .esxi_adoption import build_esxi_adoption_plan
    from .esxi_runtime import execute_esxi_runtime
    from .netbox_full_apply import apply_full_sync
    review = (build_proxmox_review(nb_api, hosts, config) if config.source_type == 'proxmox'
              else build_esxi_review(build_esxi_adoption_plan(nb_api, hosts, config), config))
    review_plan = plan_from_review(review, config)
    if not review_plan.apply_allowed:
        return review_plan
    planning_api = PlanningNetBox(nb_api)
    if config.source_type == 'proxmox':
        apply_full_sync(planning_api, hosts, config.target, confirmed=True)
    else:
        execute_esxi_runtime(planning_api, hosts, config, confirmed=True)
    return plan_from_mutations(review, config, planning_api.mutations)


def execute_child(payload):
    """Re-plan and optionally cross the guarded write boundary."""
    import pynetbox
    from .esxi_runtime import execute_esxi_runtime
    from .netbox_full_apply import apply_full_sync
    config, hosts = _discover(payload)
    nb_api = pynetbox.api(payload['netbox_url'], token=payload['netbox_token'])
    plan = _plan(nb_api, hosts, config)
    if payload['operation'] == 'plan':
        return {**plan.canonical_dict(), 'digest': plan.digest}
    if not plan.apply_allowed or plan.digest != payload.get('expected_digest'):
        raise ApplyWorkerError('PLAN_STALE')
    # Prove all provider-specific prechecks before entering the write call.
    try:
        if config.source_type == 'proxmox':
            apply_full_sync(nb_api, hosts, config.target, confirmed=False)
        else:
            execute_esxi_runtime(nb_api, hosts, config, confirmed=False)
    except Exception as exc:
        raise ApplyWorkerError('FAILED_BEFORE_WRITE') from exc
    try:
        if config.source_type == 'proxmox':
            apply_full_sync(nb_api, hosts, config.target, confirmed=True)
        else:
            execute_esxi_runtime(nb_api, hosts, config, confirmed=True)
    except Exception as exc:
        raise ApplyWorkerError('OUTCOME_UNCERTAIN') from exc
    return {'status': 'SUCCEEDED', 'plan_digest': plan.digest}


def child_main():
    """Execute without logging secrets or exception text."""
    try:
        payload = json.loads(sys.stdin.buffer.read(MAX_RESPONSE + 1))
        result = {'result': execute_child(payload)}
    except ApplyWorkerError as exc:
        result = {'error': exc.code}
    except Exception:  # pylint: disable=broad-exception-caught
        result = {'error': 'APPLY_FAILED'}
    sys.stdout.write(json.dumps(result))


class ApplySupervisor:
    """Own credentials, confirmation state, child lifecycle, and the shared apply lock."""

    def __init__(self, dsn, schema, secret_root, source_secret_root, netbox_url,
                 netbox_token_file, lock_path, child_uid=10001, child_gid=10001,
                 popen=subprocess.Popen, confirmations=None):
        self._dsn, self._schema = dsn, schema
        self._secret_root, self._source_secret_root = secret_root, source_secret_root
        self._netbox_url, self._netbox_token_file = netbox_url, netbox_token_file
        self._lock_path = lock_path
        self._child_uid, self._child_gid, self._popen = child_uid, child_gid, popen
        self._confirmations = confirmations or ConfirmationStore()

    def _source(self, instance):
        try:
            registry = SourceRegistry(lambda: psycopg.connect(
                self._dsn, connect_timeout=3,
                options='-c statement_timeout=3000 -c default_transaction_read_only=on'), self._schema)
            if registry.schema_version() != 1:
                raise ApplyWorkerError('REGISTRY_UNAVAILABLE')
            record = registry.get_by_source_instance(instance)
        except ApplyWorkerError:
            raise
        except Exception:
            raise ApplyWorkerError('REGISTRY_UNAVAILABLE') from None
        if record is None:
            raise ApplyWorkerError('SOURCE_NOT_FOUND')
        if not record.config.enabled:
            raise ApplyWorkerError('SOURCE_DISABLED')
        return record.config

    def _payload(self, config, operation, expected_digest=None):
        from .secret_resolver import FileSecretResolver, SecretResolutionError
        try:
            credentials = FileSecretResolver(
                secret_root=self._secret_root, source_secret_root=self._source_secret_root,
                max_secret_bytes=4096).resolve_credentials(config.credentials)
            token = _bounded_secret(self._netbox_token_file)
        except (SecretResolutionError, OSError):
            raise ApplyWorkerError('CREDENTIAL_UNAVAILABLE') from None
        return {'source': _config_payload(config), 'credentials': asdict(credentials),
                'netbox_url': self._netbox_url, 'netbox_token': token,
                'operation': operation, 'expected_digest': expected_digest}

    def _child(self, payload):
        operation = payload['operation']
        raw = json.dumps(payload).encode()
        try:
            with self._popen([sys.executable, '-B', '-m', 'netbox_pve_sync.apply_worker', '--child'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=_safe_environment(), preexec_fn=_drop_privileges(
                                 self._child_uid, self._child_gid) if os.name == 'posix' else None) as process:
                try:
                    output, _ = process.communicate(raw, timeout=CHILD_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    code = ('FAILED_BEFORE_WRITE' if operation == 'plan'
                            else 'OUTCOME_UNCERTAIN')
                    raise ApplyWorkerError(code) from None
        finally:
            raw = b''
            payload = None
        if process.returncode or len(output) > MAX_RESPONSE:
            raise ApplyWorkerError('FAILED_BEFORE_WRITE' if operation == 'plan'
                                   else 'OUTCOME_UNCERTAIN')
        try:
            response = json.loads(output)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApplyWorkerError('FAILED_BEFORE_WRITE' if operation == 'plan'
                                   else 'OUTCOME_UNCERTAIN') from None
        if not isinstance(response, dict) or set(response) - {'result', 'error'}:
            raise ApplyWorkerError('FAILED_BEFORE_WRITE' if operation == 'plan'
                                   else 'OUTCOME_UNCERTAIN')
        if response.get('error'):
            allowed = {'PLAN_STALE', 'PLAN_BLOCKED', 'FAILED_BEFORE_WRITE',
                       'OUTCOME_UNCERTAIN', 'APPLY_FAILED', 'SOURCE_UNSUPPORTED'}
            code = response['error'] if response['error'] in allowed else 'APPLY_FAILED'
            raise ApplyWorkerError(code)
        if not isinstance(response.get('result'), dict):
            raise ApplyWorkerError('APPLY_FAILED')
        return response['result']

    def prepare(self, instance, digest):
        """Recompute plan and issue a capability only for an exact safe match."""
        config = self._source(instance)
        plan = self._child(self._payload(config, 'plan'))
        if not plan['apply_allowed']:
            raise ApplyWorkerError('PLAN_BLOCKED')
        if plan['digest'] != digest:
            raise ApplyWorkerError('PLAN_STALE')
        claims = ConfirmationClaims(instance, config.id, digest, plan['planner_version'],
                                    plan['source_fingerprint'], plan['target_fingerprint'])
        return {'confirmation_token': self._confirmations.issue(claims),
                'expires_in_seconds': 300}

    def apply(self, instance, token):
        """Consume, lock, reload and recompute before any write."""
        try:
            claims = self._confirmations.consume(token, instance)
        except ConfirmationError as exc:
            raise ApplyWorkerError(exc.code) from exc
        import fcntl  # pylint: disable=import-outside-toplevel
        lock_fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ApplyWorkerError('APPLY_LOCKED') from None
            config = self._source(instance)
            if config.id != claims.source_id:
                raise ApplyWorkerError('PLAN_STALE')
            result = self._child(self._payload(config, 'apply', claims.plan_digest))
            if result.get('plan_digest') != claims.plan_digest:
                raise ApplyWorkerError('PLAN_STALE')
            return result
        finally:
            os.close(lock_fd)


def _receive(connection):
    connection.settimeout(5)
    chunks = []
    size = 0
    while True:
        chunk = connection.recv(min(4096, MAX_REQUEST + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_REQUEST:
            raise ApplyWorkerError('REQUEST_INVALID')
        chunks.append(chunk)
    raw = b''.join(chunks)
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApplyWorkerError('REQUEST_INVALID') from None
    operation = request.get('operation') if isinstance(request, dict) else None
    allowed = ({'operation', 'source_instance', 'plan_digest'} if operation == 'prepare'
               else {'operation', 'source_instance', 'confirmation_token'})
    if (not isinstance(request, dict) or set(request) != allowed
            or operation not in ('prepare', 'apply')
            or not SOURCE_INSTANCE_PATTERN.fullmatch(request.get('source_instance', ''))
            or (operation == 'prepare' and not DIGEST_PATTERN.fullmatch(
                request.get('plan_digest', '')))
            or (operation == 'apply' and not TOKEN_PATTERN.fullmatch(
                request.get('confirmation_token', '')))):
        raise ApplyWorkerError('REQUEST_INVALID')
    return request


def _authorize(connection, uid):
    if not hasattr(socket, 'SO_PEERCRED'):
        raise ApplyWorkerError('PEER_FORBIDDEN')
    _pid, peer_uid, _gid = struct.unpack('3i', connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if peer_uid != uid:
        raise ApplyWorkerError('PEER_FORBIDDEN')


def serve(socket_path, supervisor, allowed_uid):
    """Serve only fixed prepare/apply operations to the API UID."""
    path = Path(socket_path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        os.chown(path, 0, allowed_uid)
        os.chmod(path, 0o660)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    _authorize(connection, allowed_uid)
                    request = _receive(connection)
                    result = (supervisor.prepare(request['source_instance'], request['plan_digest'])
                              if request['operation'] == 'prepare' else
                              supervisor.apply(request['source_instance'],
                                               request['confirmation_token']))
                    response = {'ok': True, 'result': result}
                except ApplyWorkerError as exc:
                    response = {'ok': False, 'error': exc.code}
                except Exception:  # pylint: disable=broad-exception-caught
                    response = {'ok': False, 'error': 'WORKER_INTERNAL_ERROR'}
                connection.sendall(json.dumps(response).encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--socket')
    parser.add_argument('--secret-root')
    parser.add_argument('--source-secret-root')
    parser.add_argument('--netbox-token-file')
    parser.add_argument('--lock-path', default='/run/infra-sync/apply.lock')
    parser.add_argument('--api-uid', type=int, default=10001)
    parser.add_argument('--child-uid', type=int, default=10001)
    parser.add_argument('--child-gid', type=int, default=10001)
    args = parser.parse_args()
    if args.child:
        child_main()
        return
    supervisor = ApplySupervisor(
        os.environ.get('INFRA_SYNC_APPLY_REGISTRY_DSN', ''),
        os.environ.get('INFRA_SYNC_REGISTRY_SCHEMA', ''), args.secret_root,
        args.source_secret_root, os.environ.get('INFRA_SYNC_APPLY_NB_API_URL', ''),
        args.netbox_token_file, args.lock_path, args.child_uid, args.child_gid)
    serve(args.socket, supervisor, args.api_uid)


if __name__ == '__main__':
    main()
