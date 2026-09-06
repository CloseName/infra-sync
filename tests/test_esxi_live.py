"""Explicitly opted-in, read-only live standalone ESXi connection test."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from netbox_sync.esxi_client import (
    EsxiClient,
    test_source_connection as check_source_connection,
)
from netbox_sync.secret_resolver import FileSecretResolver
from netbox_sync.source_config import SecretReference, SourceCredentials

from tests.sample_data import sample_source_config


LIVE_VARIABLES = (
    'NETBOX_SYNC_TEST_ESXI_HOST',
    'NETBOX_SYNC_TEST_ESXI_USER',
    'NETBOX_SYNC_TEST_ESXI_PASSWORD_FILE',
)


def test_live_esxi_connection_is_read_only_and_explicitly_opted_in():
    values = {name: os.environ.get(name, '').strip() for name in LIVE_VARIABLES}
    if not all(values.values()):
        pytest.skip('live ESXi connection variables are not configured')

    password_path = Path(values['NETBOX_SYNC_TEST_ESXI_PASSWORD_FILE'])
    password_reference = SecretReference(
        provider='file',
        key=password_path.name,
    )
    config = replace(
        sample_source_config(address=values['NETBOX_SYNC_TEST_ESXI_HOST']),
        id='esxi-live-test',
        source_instance='esxi-live-test',
        source_type='esxi',
        legacy_identity_owner=False,
        verify_ssl=True,
        credentials=SourceCredentials.for_password(
            values['NETBOX_SYNC_TEST_ESXI_USER'],
            password_reference,
        ),
    )
    client = EsxiClient(
        resolver=FileSecretResolver(secret_root=password_path.parent)
    )

    result = check_source_connection(config, client=client)

    assert result.success, result.summary
