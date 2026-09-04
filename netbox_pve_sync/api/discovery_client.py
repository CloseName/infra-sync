"""Credential-blind client for the dedicated local discovery worker."""
# pylint: disable=too-few-public-methods

import json
import socket

from ..source_config import SOURCE_INSTANCE_PATTERN


class DiscoveryRequestError(RuntimeError):
    """A stable, secret-free discovery transport failure."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class DiscoveryWorkerClient:
    """Send a source identity only over the dedicated local socket."""
    def __init__(self, socket_path, connector=socket.socket):
        self._socket_path = socket_path
        self._connector = connector

    def _request(self, source_instance, operation):
        if not SOURCE_INSTANCE_PATTERN.fullmatch(source_instance):
            raise DiscoveryRequestError('SOURCE_NOT_FOUND')
        if not self._socket_path:
            raise DiscoveryRequestError('DISCOVERY_UNAVAILABLE')
        request = json.dumps({'source_instance': source_instance, 'operation': operation}).encode()
        try:
            with self._connector(socket.AF_UNIX, socket.SOCK_STREAM) as connection:  # pylint: disable=no-member
                connection.settimeout(125)
                connection.connect(self._socket_path)
                connection.sendall(request)
                connection.shutdown(socket.SHUT_WR)
                chunks = []
                size = 0
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ValueError('response too large')
                    chunks.append(chunk)
            response = json.loads(b''.join(chunks))
        except (OSError, ValueError, json.JSONDecodeError):
            raise DiscoveryRequestError('DISCOVERY_UNAVAILABLE') from None
        if not isinstance(response, dict) or set(response) - {'ok', 'result', 'error'}:
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        if response.get('ok') is not True:
            code = response.get('error')
            allowed = {'SOURCE_NOT_FOUND', 'SOURCE_DISABLED', 'CREDENTIAL_UNAVAILABLE',
                       'REGISTRY_UNAVAILABLE', 'DISCOVERY_TIMEOUT', 'PROVIDER_UNAVAILABLE',
                       'NETBOX_UNAVAILABLE', 'DISCOVERY_FAILED'}
            raise DiscoveryRequestError(code if code in allowed else 'DISCOVERY_UNAVAILABLE')
        if not isinstance(response.get('result'), dict):
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        return response['result']

    def discover(self, source_instance):
        """Request one ephemeral discovery result."""
        return self._request(source_instance, 'discover')

    def plan(self, source_instance):
        """Request one canonical read-only sync plan."""
        return self._request(source_instance, 'plan')
