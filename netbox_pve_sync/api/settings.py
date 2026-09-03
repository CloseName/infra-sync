"""Snapshot API configuration once at bootstrap, not inside domain services."""

import os
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version


@dataclass(frozen=True)
class ApiSettings:
    """Reuse registry conventions; no source or NetBox credential resolution."""

    registry_dsn: str = field(default='', repr=False)
    registry_schema: str = ''
    netbox_configured: bool = False
    web_dist: str = field(default='', repr=False)

    @classmethod
    def from_environment(cls, environ=None):
        """Read only required configuration; never log or serialize the environment."""
        env = os.environ if environ is None else environ
        return cls(
            registry_dsn=env.get('INFRA_SYNC_REGISTRY_DSN', '').strip(),
            registry_schema=env.get('INFRA_SYNC_REGISTRY_SCHEMA', '').strip(),
            netbox_configured=bool(
                env.get('NB_API_URL', '').strip()
                and (env.get('NB_API_TOKEN', '').strip() or env.get('NB_API_TOKEN_FILE', '').strip())
            ),
            web_dist=env.get('INFRA_SYNC_WEB_DIST', '').strip(),
        )


def application_version():
    """Distribution version, with a deterministic fallback for uninstalled checkouts."""
    try:
        return version('netbox-pve-sync')
    except PackageNotFoundError:
        return 'development'
