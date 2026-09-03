"""In-memory test doubles for external APIs."""

from .netbox import FakeNetBox, FakeRecord
from .proxmox import FakeProxmox

__all__ = (
    'FakeNetBox',
    'FakeProxmox',
    'FakeRecord',
)
