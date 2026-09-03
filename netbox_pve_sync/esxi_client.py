"""Safe pyVmomi connection and session boundary for standalone ESXi."""

import ssl
from contextlib import contextmanager
from dataclasses import dataclass

from .secret_resolver import FileSecretResolver


class EsxiConnectionError(RuntimeError):
    """An ESXi authentication, TLS, or API connection failed safely."""


@dataclass(frozen=True)
class SourceConnectionResult:
    """Secret-free result suitable for a future connection-test API."""

    source_id: str
    success: bool
    error_type: str = None
    summary: str = None


def _pyvmomi_connect(host, username, password, verify_ssl):
    from pyVim.connect import SmartConnect  # pylint: disable=import-outside-toplevel

    context = (
        ssl.create_default_context()
        if verify_ssl
        else ssl._create_unverified_context()  # pylint: disable=protected-access
    )
    return SmartConnect(
        host=host,
        user=username,
        pwd=password,
        sslContext=context,
    )


def _pyvmomi_disconnect(service_instance):
    from pyVim.connect import Disconnect  # pylint: disable=import-outside-toplevel

    Disconnect(service_instance)


class EsxiClient:
    """Resolve credentials at connection time and always close the API session."""

    def __init__(
            self,
            resolver=None,
            connector=None,
            disconnecter=None,
    ):
        self._resolver = resolver or FileSecretResolver()
        self._connector = connector or _pyvmomi_connect
        self._disconnecter = disconnecter or _pyvmomi_disconnect

    @contextmanager
    def session(self, source_config):
        """Yield a connected service instance and deterministically disconnect."""

        password = self._resolver.resolve(
            source_config.credentials.password_reference
        )
        try:
            service_instance = self._connector(
                source_config.address,
                source_config.credentials.username,
                password,
                source_config.verify_ssl,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            raise EsxiConnectionError('ESXi connection failed') from None

        try:
            yield service_instance
        finally:
            try:
                self._disconnecter(service_instance)
            except Exception:  # pylint: disable=broad-exception-caught
                pass


def test_source_connection(source_config, client=None):
    """Read basic ESXi API metadata and return only a safe status."""

    if source_config.source_type != 'esxi':
        raise ValueError('ESXi connection test requires source_type=esxi')
    api_client = client or EsxiClient()
    try:
        with api_client.session(source_config) as service_instance:
            content = service_instance.RetrieveContent()
            if content is None:
                raise EsxiConnectionError('ESXi API returned no content')
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return SourceConnectionResult(
            source_id=source_config.id,
            success=False,
            error_type=type(exc).__name__,
            summary='ESXi connection test failed',
        )
    return SourceConnectionResult(
        source_id=source_config.id,
        success=True,
        summary='ESXi connection test succeeded',
    )
