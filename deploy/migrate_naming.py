#!/usr/bin/env python3
"""Explicit, fail-closed transition from the legacy product env namespace."""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import install


CONFIRMATION = 'MIGRATE_INFRA_SYNC_ENV_TO_NETBOX_SYNC'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Preflight NetBox Sync naming transition')
    parser.add_argument('--root', type=Path, default=Path('/opt/infra-sync'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.apply and args.confirm != CONFIRMATION:
        print('naming migration confirmation is required', file=sys.stderr)
        return 2
    try:
        count = install.migrate_legacy_environment(args.root, apply=args.apply)
    except (install.InstallError, OSError):
        print('naming migration preflight failed; config values were not displayed', file=sys.stderr)
        return 1
    action = 'migrated' if args.apply else 'would migrate'
    print(f'{action} {count} reviewed environment keys')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
