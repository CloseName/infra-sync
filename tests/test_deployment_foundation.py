"""Static and unit contracts for the reproducible v1 deployment foundation."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from deploy import install
from netbox_pve_sync import deployment


ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / 'compose.production.yml'


def test_canonical_compose_has_private_bundled_postgres_and_one_app_image():
    text = COMPOSE.read_text(encoding='utf-8')
    assert 'postgres:16-bookworm' in text
    postgres = text.split('  postgres:', 1)[1].split('  infra-sync-api:', 1)[0]
    assert 'infra-sync-postgres:/var/lib/postgresql/data' in postgres
    assert 'pg_isready' in postgres
    assert 'ports:' not in postgres
    assert 'internal: true' in text
    assert 'x-app: &app' in text
    assert text.count('dockerfile: Dockerfile.web') == 1
    assert 'container_name:' not in text
    assert 'name: ${INFRA_SYNC_COMPOSE_PROJECT:-infra-sync}' in text
    for service in ('infra-sync-api', 'infra-sync-discovery-worker',
                    'infra-sync-apply-worker', 'infra-sync-schedule-worker',
                    'infra-sync-secret-broker', 'infra-sync-scheduler'):
        assert f'  {service}:' in text


def test_external_postgres_override_is_explicit_and_optional():
    override = (ROOT / 'compose.external-postgres.yml').read_text(encoding='utf-8')
    assert 'postgres:' in override
    assert 'profiles: [bundled-postgres]' in override
    assert 'infra-sync-api:' in override and 'infra-sync-egress' in override
    assert 'infra-sync-schedule-worker:' in override
    assert 'infra-sync-migrate:' in override


def test_canonical_compose_removes_historical_host_coupling():
    text = COMPOSE.read_text(encoding='utf-8')
    assert 'netbox_default' not in text
    assert 'docker.sock' not in text
    assert '/app/netbox_pve_sync' not in text
    assert 'proxmox_token' not in text
    assert 'esxi_infra' not in text
    assert 'legacy-sources' not in text
    assert '${INFRA_SYNC_SOURCE_SECRET_DIR' in text


def test_worker_network_and_credential_boundaries_are_preserved():
    text = COMPOSE.read_text(encoding='utf-8')
    api = text.split('  infra-sync-api:', 1)[1].split('  infra-sync-secret-broker:', 1)[0]
    broker = text.split('  infra-sync-secret-broker:', 1)[1].split(
        '  infra-sync-discovery-worker:', 1)[0]
    discovery = text.split('  infra-sync-discovery-worker:', 1)[1].split(
        '  infra-sync-apply-worker:', 1)[0]
    apply = text.split('  infra-sync-apply-worker:', 1)[1].split(
        '  infra-sync-schedule-worker:', 1)[0]
    schedule = text.split('  infra-sync-schedule-worker:', 1)[1].split(
        '  infra-sync-scheduler:', 1)[0]
    assert 'network_mode: none' in broker
    assert 'cap_add: [CHOWN]' in broker
    assert 'networks: [infra-sync-db, infra-sync-web]' in api
    assert 'infra-sync-db, infra-sync-egress' in discovery
    assert 'infra-sync-db, infra-sync-egress' in apply
    assert 'networks: [infra-sync-db]' in schedule
    assert 'infra-sync-egress' not in schedule
    assert 'source-secrets' not in api
    assert 'netbox/apply-token' not in api
    assert 'RUN_WRITER' not in api
    assert 'REGISTRATION' not in discovery + apply + schedule


def test_root_only_secrets_are_read_only_and_limited_to_required_processes():
    text = COMPOSE.read_text(encoding='utf-8')
    for service, following in (
            ('infra-sync-scheduler', 'infra-sync-db-roles'),
            ('infra-sync-db-roles', 'infra-sync-migrate'),
            ('infra-sync-migrate', 'infra-sync-db-grants')):
        block = text.split(f'  {service}:', 1)[1].split(f'  {following}:', 1)[0]
        assert 'user: "0:0"' in block
        assert ':ro' in block
    tools = text.split('  infra-sync-db-roles:', 1)[1]
    assert '/run/secrets/infra-sync-db:ro' in tools


def test_canonical_compose_renders_without_provider_configuration():
    if not shutil_which('docker'):
        pytest.skip('Docker CLI is unavailable')
    result = subprocess.run(
        ['docker', 'compose', '-f', str(COMPOSE), 'config', '--quiet'],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def shutil_which(name):
    """Local wrapper keeps pylint from mistaking a test import for installer state."""
    import shutil  # pylint: disable=import-outside-toplevel
    return shutil.which(name)


def test_tracked_systemd_path_has_exactly_one_shared_lock():
    service = (ROOT / 'deploy/systemd/infra-netbox-sync.service').read_text(encoding='utf-8')
    wrapper = (ROOT / 'scripts/run-scheduled-sync.sh').read_text(encoding='utf-8')
    combined = service + wrapper
    assert 'ExecStart=/opt/infra-sync/current/scripts/run-scheduled-sync.sh' in service
    assert combined.count('/usr/bin/flock') == 1
    assert '/run/infra-sync/apply.lock' in wrapper
    assert '--remove-orphans' not in wrapper
    assert 'compose.production.yml' in wrapper
    assert '--env-file' in wrapper
    timer = (ROOT / 'deploy/systemd/infra-netbox-sync.timer').read_text(encoding='utf-8')
    assert 'OnUnitActiveSec=60s' in timer
    assert 'AccuracySec=5s' in timer


def test_scheduler_example_uses_actual_registry_all_runtime_boundary():
    environment = (ROOT / 'deploy/examples/scheduler.env').read_text(encoding='utf-8')
    assert 'SOURCE_CONFIG_MODE=registry-all' in environment
    assert 'SYNC_SOURCE_MODE' not in environment


def test_canonical_scripts_never_shell_source_env_files():
    for path in (ROOT / 'scripts').glob('*.sh'):
        text = path.read_text(encoding='utf-8')
        assert 'source ' not in text
        assert '. compose.env' not in text
        assert '.env' not in text or '--env-file' in text


def test_secret_creation_is_exclusive_0600_and_does_not_change_umask(tmp_path):
    path = tmp_path / 'secret'
    before = os.umask(0o022)
    os.umask(before)
    install.write_secret_exclusive(path, 'not-a-real-secret')
    observed = os.umask(0o077)
    os.umask(observed)
    assert observed == before
    if os.name == 'posix':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        install.write_secret_exclusive(path, 'replacement')
    assert path.read_text(encoding='utf-8') == 'not-a-real-secret\n'


def test_existing_secret_is_reused_and_never_regenerated(tmp_path):
    path = tmp_path / 'owner_password'
    values = iter(('first', 'second'))
    assert install.ensure_secret(path, lambda: next(values)) == 'first'
    assert install.ensure_secret(path, lambda: next(values)) == 'first'


def test_generated_configuration_is_role_separated_and_idempotent(tmp_path):
    for relative in ('config', 'secrets/infrastructure', 'secrets/sources',
                     'secrets/netbox'):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    install.generate_configuration(tmp_path, 'infra-sync-app:test-release')
    owner = (tmp_path / 'secrets/infrastructure/owner_password').read_bytes()
    install.generate_configuration(tmp_path, 'infra-sync-app:test-release')
    assert (tmp_path / 'secrets/infrastructure/owner_password').read_bytes() == owner
    api = (tmp_path / 'config/api.env').read_text(encoding='utf-8')
    discovery = (tmp_path / 'config/discovery.env').read_text(encoding='utf-8')
    apply = (tmp_path / 'config/apply.env').read_text(encoding='utf-8')
    schedule = (tmp_path / 'config/schedule.env').read_text(encoding='utf-8')
    assert 'infra_sync_web_reader' in api and 'infra_sync_registration_writer' in api
    assert 'infra_sync_discovery_reader' in discovery
    assert 'infra_sync_apply_registry_reader' in apply and 'infra_sync_run_writer' in apply
    assert 'infra_sync_schedule_writer' in schedule
    assert 'PVE_' not in api + discovery + apply + schedule


def test_env_file_preserves_libpq_spaces_without_shell_parsing(tmp_path):
    path = tmp_path / 'service.env'
    value = "host=postgres dbname=infra_sync user=test password='contains spaces'"
    install.write_config(path, {'DATABASE_DSN': value})
    assert path.read_text(encoding='utf-8') == f'DATABASE_DSN={value}\n'
    if os.name == 'posix':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_release_permission_normalization_excludes_secret_policy(tmp_path):
    if os.name != 'posix':
        pytest.skip('POSIX modes are not represented by the Windows filesystem')
    root = tmp_path / 'release'
    script = root / 'scripts' / 'run.sh'
    code = root / 'netbox_pve_sync' / 'module.py'
    script.parent.mkdir(parents=True)
    code.parent.mkdir(parents=True)
    script.write_text('#!/bin/sh\n', encoding='utf-8')
    code.write_text('VALUE = 1\n', encoding='utf-8')
    install.normalize_release_permissions(root)
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    assert stat.S_IMODE(code.stat().st_mode) == 0o644


def test_database_role_matrix_is_complete_and_has_no_secret_literals():
    assert set(deployment.DATABASE_ROLES) == {
        'owner', 'web_reader', 'registration_writer', 'discovery_reader',
        'apply_registry_reader', 'registry_reader', 'run_writer', 'schedule_writer',
    }
    source = (ROOT / 'netbox_pve_sync/deployment.py').read_text(encoding='utf-8')
    assert 'DELETE' not in source
    assert 'TRUNCATE' not in source
    assert 'sql.Literal(password)' in source


def test_database_tool_sanitizes_failures(monkeypatch, capsys):
    marker = 'SENSITIVE_VALUE_MUST_NOT_LEAK'
    monkeypatch.setattr(deployment, 'bootstrap_roles', lambda: (_ for _ in ()).throw(
        RuntimeError(marker)))
    assert deployment.main(['bootstrap-roles']) == 1
    output = capsys.readouterr()
    assert marker not in output.out + output.err
    assert 'bootstrap-roles failed' in output.err


def test_lf_policy_covers_deployment_artifacts():
    attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
    for pattern in ('*.py text eol=lf', '*.sh text eol=lf', '*.yml text eol=lf',
                    '*.service text eol=lf', '*.timer text eol=lf'):
        assert pattern in attributes
