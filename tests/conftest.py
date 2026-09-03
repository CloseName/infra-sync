"""Shared fixtures for isolated sync tests."""

import pytest

from tests.fakes import FakeNetBox, FakeProxmox


@pytest.fixture
def fake_netbox():
    return FakeNetBox()


@pytest.fixture
def fake_proxmox():
    return FakeProxmox()
