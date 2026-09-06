"""Explicit disposable-volume smoke helper, never auto-run and never production data."""

import os
import stat
import sys
from pathlib import Path

from netbox_sync.api.onboarding_adapters import BrokerSecretStore
from netbox_sync.secret_resolver import FileSecretResolver
from netbox_sync.source_config import SecretReference, SourceCredentials

KEY_ID = 'src-smoke-token-id-0123456789abcdef'
KEY_SECRET = 'src-smoke-secret-0123456789abcdef'
KEY_ESXI = 'src-smoke-esxi-0123456789abcdef'


def main(mode):
    """Only fixed temporary mount paths; all values are explicitly fake."""
    if mode == 'setup':
        assert os.getuid() == 0
        os.chmod('/secrets', 0o700)
        Path('/legacy/esxi_infra_sync_password').write_text('FAKE_LEGACY_PASSWORD', encoding='utf-8')
    elif mode == 'client':
        assert os.getuid() == 10001
        info = os.stat('/run/broker/broker.sock')
        assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 10001, 0o660)
        assert not Path('/secrets').exists()
        store = BrokerSecretStore('/run/broker/broker.sock')
        receipts = [store.create(KEY_ID, 'FAKE_TOKEN_ID'), store.create(KEY_SECRET, 'FAKE_TOKEN_SECRET'),
                    store.create(KEY_ESXI, 'FAKE_ESXI_PASSWORD')]
        store.forget(receipts)
        assert not store._operations
        receipt = store.create('src-smoke-rollback-0123456789abcdef', 'FAKE_ROLLBACK')
        store.rollback(receipt)
    elif mode == 'runtime':
        resolver = FileSecretResolver()
        credentials = SourceCredentials('fake-user', SecretReference('file', KEY_ID), SecretReference('file', KEY_SECRET))
        resolved = resolver.resolve_credentials(credentials)
        assert resolved.token_id == 'FAKE_TOKEN_ID' and resolved.token_secret == 'FAKE_TOKEN_SECRET'
        assert resolver.resolve(SecretReference('file', KEY_ESXI)) == 'FAKE_ESXI_PASSWORD'
        assert resolver.resolve(SecretReference('file', 'esxi_infra_sync_password')) == 'FAKE_LEGACY_PASSWORD'
        path = Path('/run/secrets/netbox-sync-sources') / KEY_SECRET
        info = path.stat()
        assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 0, 0o600)
        try:
            path.open('a').close()
        except OSError:
            pass
        else:
            raise AssertionError('Runtime secret mount must be read-only')
    else:
        raise ValueError('Unsupported smoke mode')
    print('PASS: disposable WEB-3 ' + mode)


if __name__ == '__main__':
    main(sys.argv[1])
