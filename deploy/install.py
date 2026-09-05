#!/usr/bin/env python3
"""Minimal non-interactive foundation installer for a fresh Debian host."""

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote


ROLE_USERS = {
    'owner': 'infra_sync_owner',
    'web_reader': 'infra_sync_web_reader',
    'registration_writer': 'infra_sync_registration_writer',
    'discovery_reader': 'infra_sync_discovery_reader',
    'apply_registry_reader': 'infra_sync_apply_registry_reader',
    'registry_reader': 'infra_sync_registry_reader',
    'run_writer': 'infra_sync_run_writer',
    'schedule_writer': 'infra_sync_schedule_writer',
}
PASSWORD_NAMES = ('postgres_bootstrap', *ROLE_USERS)
RELEASE_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
IGNORED_NAMES = frozenset({
    '.git', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.coverage', 'coverage.xml',
    'htmlcov', 'build', 'dist', 'node_modules', '__pycache__', '.codex-test-tmp',
    '.venv', 'venv', '.idea', '.vscode',
})


class InstallError(RuntimeError):
    """Safe installation failure."""


def run(command, *, check=True):
    """Run a fixed operator command without shell parsing."""
    return subprocess.run(command, check=check, text=True)  # noqa: S603


def validate_prerequisites(*, require_systemd=True):
    """Verify required host tools without writing host state."""
    if sys.version_info < (3, 10):
        raise InstallError('Python 3.10 or newer is required')
    for executable in ('docker', 'install', 'flock'):
        if shutil.which(executable) is None:
            raise InstallError(f'required executable is missing: {executable}')
    result = run(['docker', 'compose', 'version'], check=False)
    if result.returncode:
        raise InstallError('Docker Compose v2 is required')
    if require_systemd and shutil.which('systemctl') is None:
        raise InstallError('systemd is required unless --no-systemd is used')


def ensure_directory(path, mode):
    """Create or normalize one non-secret layout directory."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)


def write_secret_exclusive(path, value):
    """Create one secret atomically without changing process-global umask."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, (value + '\n').encode('utf-8'))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_secret(path, generator=lambda: secrets.token_urlsafe(36)):
    """Generate once; reruns never rotate or overwrite an existing secret."""
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise InstallError(f'invalid existing secret path: {path.name}')
        path.chmod(0o600)
        value = path.read_text(encoding='utf-8').rstrip('\r\n')
        if not value or '\n' in value or '\r' in value:
            raise InstallError(f'invalid existing secret file: {path.name}')
        return value
    value = generator()
    write_secret_exclusive(path, value)
    return value


def normalize_release_permissions(root):
    """Make packaged code readable while never traversing persistent secrets."""
    for path in root.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.suffix == '.sh' or path == root / 'deploy' / 'install.py':
            path.chmod(0o755)
        else:
            path.chmod(0o644)


def _ignore(_directory, names):
    return [name for name in names if (name in IGNORED_NAMES or name.endswith(('.pyc', '.log'))
                                       or name == '.env' or name.endswith('.env'))]


def install_release(source, releases, release_id):
    """Copy an immutable release once and normalize its public code modes."""
    destination = releases / release_id
    if not destination.exists():
        shutil.copytree(source, destination, ignore=_ignore)
    normalize_release_permissions(destination)
    return destination


def activate_release(root, release):
    """Atomically point current at the selected immutable release."""
    current = root / 'current'
    if current.is_symlink() and current.resolve() == release.resolve():
        return
    temporary = root / f'.current-{os.getpid()}'
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    temporary.symlink_to(release, target_is_directory=True)
    os.replace(temporary, current)


def _dsn(user, password):
    return (f'postgresql://{quote(user, safe="")}:{quote(password, safe="")}@'
            'postgres:5432/infra_sync?connect_timeout=5')


def write_config(path, values):
    """Write a protected Docker env-file; it is deliberately not shell syntax."""
    temporary = path.with_name(path.name + f'.tmp-{os.getpid()}')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        payload = ''.join(f'{key}={value}\n' for key, value in values.items())
        os.write(descriptor, payload.encode('utf-8'))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(0o600)


def generate_configuration(root, image):
    """Generate role-separated env files from protected infrastructure secrets."""
    secret_root, config = root / 'secrets' / 'infrastructure', root / 'config'
    passwords = {
        name: ensure_secret(secret_root / f'{name}_password') for name in PASSWORD_NAMES
    }
    dsns = {key: _dsn(user, passwords[key]) for key, user in ROLE_USERS.items()}
    common = {'INFRA_SYNC_REGISTRY_SCHEMA': 'infra_sync'}
    write_config(config / 'compose.env', {
        'INFRA_SYNC_COMPOSE_PROJECT': 'infra-sync',
        'INFRA_SYNC_IMAGE': image,
        'INFRA_SYNC_CONFIG_DIR': str(config),
        'INFRA_SYNC_INFRA_SECRET_DIR': str(secret_root),
        'INFRA_SYNC_SOURCE_SECRET_DIR': str(root / 'secrets' / 'sources'),
        'INFRA_SYNC_NETBOX_SECRET_DIR': str(root / 'secrets' / 'netbox'),
        'INFRA_SYNC_APPLY_LOCK_DIR': '/run/infra-sync',
        'INFRA_SYNC_POSTGRES_VOLUME': 'infra-sync-postgres-data',
    })
    write_config(config / 'api.env', {
        **common, 'INFRA_SYNC_REGISTRY_DSN': dsns['web_reader'],
        'INFRA_SYNC_REGISTRATION_DSN': dsns['registration_writer'],
        'INFRA_SYNC_BROKER_SOCKET': '/run/infra-sync-broker/broker.sock',
        'INFRA_SYNC_DISCOVERY_SOCKET': '/run/infra-sync-discovery/worker.sock',
        'INFRA_SYNC_APPLY_SOCKET': '/run/infra-sync-apply/worker.sock',
        'INFRA_SYNC_SCHEDULE_SOCKET': '/run/infra-sync-schedule/worker.sock',
        'NB_API_URL': '', 'NB_API_TOKEN_FILE': '',
        'INFRA_SYNC_WRITE_HOSTS': '127.0.0.1:8000,localhost:8000',
    })
    write_config(config / 'discovery.env', {
        **common, 'INFRA_SYNC_DISCOVERY_REGISTRY_DSN': dsns['discovery_reader'],
        'INFRA_SYNC_DISCOVERY_NB_API_URL': '',
    })
    write_config(config / 'apply.env', {
        **common, 'INFRA_SYNC_APPLY_REGISTRY_DSN': dsns['apply_registry_reader'],
        'INFRA_SYNC_RUN_WRITER_DSN': dsns['run_writer'],
        'INFRA_SYNC_APPLY_NB_API_URL': '',
    })
    write_config(config / 'schedule.env', {
        **common, 'INFRA_SYNC_SCHEDULE_WRITER_DSN': dsns['schedule_writer'],
    })
    write_config(config / 'scheduler.env', {
        **common, 'SYNC_MODE': 'apply', 'SOURCE_CONFIG_MODE': 'registry-all',
        'APPLY_SCOPE': 'full', 'APPLY_CONFIRM': 'FULL_WRITE',
        'INFRA_SYNC_REGISTRY_DSN': dsns['registry_reader'],
        'INFRA_SYNC_RUN_WRITER_DSN': dsns['run_writer'],
        'INFRA_SYNC_SOURCE_SECRET_DIR': '/run/secrets/infra-sync-sources',
        'NB_API_URL': '', 'NB_APPLY_API_TOKEN_FILE': '/run/secrets/netbox/apply-token',
    })


def prepare_layout(root, source, release_id, image):
    """Create persistent layout and atomically activate an immutable release."""
    for directory, mode in (
            (root, 0o755), (root / 'releases', 0o755), (root / 'config', 0o750),
            (root / 'secrets', 0o700), (root / 'secrets' / 'infrastructure', 0o700),
            (root / 'secrets' / 'sources', 0o700), (root / 'secrets' / 'netbox', 0o700),
            (root / 'backups', 0o700), (root / 'state', 0o750)):
        ensure_directory(directory, mode)
    release = install_release(source, root / 'releases', release_id)
    activate_release(root, release)
    generate_configuration(root, image)
    ensure_directory(Path('/run/infra-sync') if root == Path('/opt/infra-sync')
                     else root / 'run', 0o750)
    return release


def compose_command(root, *arguments):
    """Build one argv using Compose env-file semantics, never shell sourcing."""
    return ['docker', 'compose', '--env-file', str(root / 'config' / 'compose.env'),
            '-f', str(root / 'current' / 'compose.production.yml'), *arguments]


def start_stack(root):
    """Start DB, provision it, then start long-running services."""
    run(compose_command(root, 'up', '-d', 'postgres'))
    for _attempt in range(60):
        status = run(compose_command(root, 'exec', '-T', 'postgres',
                                     'pg_isready', '-U', 'infra_sync_bootstrap',
                                     '-d', 'infra_sync'), check=False)
        if status.returncode == 0:
            break
        time.sleep(2)
    else:
        raise InstallError('bundled PostgreSQL did not become healthy')
    for service in ('infra-sync-db-roles', 'infra-sync-migrate', 'infra-sync-db-grants'):
        run(compose_command(root, '--profile', 'tools', 'run', '--rm', '--no-deps', service))
    run(compose_command(root, 'up', '-d', 'infra-sync-api', 'infra-sync-secret-broker',
                        'infra-sync-discovery-worker', 'infra-sync-apply-worker',
                        'infra-sync-schedule-worker'))


def install_systemd(root, *, start=True):
    """Install tracked units idempotently; never used by tests implicitly."""
    if root != Path('/opt/infra-sync'):
        raise InstallError('systemd installation requires canonical /opt/infra-sync root')
    unit_root = root / 'current' / 'deploy' / 'systemd'
    for name in ('infra-netbox-sync.service', 'infra-netbox-sync.timer'):
        destination = Path('/etc/systemd/system') / name
        shutil.copy2(unit_root / name, destination)
        destination.chmod(0o644)
    run(['systemctl', 'daemon-reload'])
    if start:
        run(['systemctl', 'enable', '--now', 'infra-netbox-sync.timer'])


def parse_args(argv=None):
    """Parse bounded non-interactive installer options."""
    parser = argparse.ArgumentParser(description='Prepare an Infra Sync v1 foundation')
    parser.add_argument('--check', action='store_true', help='validate only; make no changes')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--no-systemd', action='store_true')
    parser.add_argument('--root', type=Path, default=Path('/opt/infra-sync'))
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--release-id', default='working-tree')
    parser.add_argument('--image', help='immutable app image/tag; defaults to the release id')
    return parser.parse_args(argv)


def main(argv=None):
    """Validate or prepare a deployment foundation."""
    args = parse_args(argv)
    if not RELEASE_PATTERN.fullmatch(args.release_id):
        raise SystemExit('invalid release id')
    try:
        validate_prerequisites(require_systemd=not args.no_systemd)
        if args.check:
            print('deployment prerequisites OK')
            return 0
        image = args.image or f'infra-sync-app:{args.release_id}'
        prepare_layout(args.root.resolve(), args.source.resolve(), args.release_id, image)
        if not args.prepare_only:
            if not args.no_start:
                start_stack(args.root.resolve())
            if not args.no_systemd:
                install_systemd(args.root.resolve(), start=not args.no_start)
    except (InstallError, OSError, subprocess.SubprocessError):
        print('deployment preparation failed; inspect host prerequisites and protected config',
              file=sys.stderr)
        return 1
    print('Infra Sync deployment foundation prepared')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
