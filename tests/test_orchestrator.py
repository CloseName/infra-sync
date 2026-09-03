"""Multi-source sequencing, dispatch, and failure-isolation tests."""

from dataclasses import replace

from netbox_pve_sync.orchestrator import run_sources
from netbox_pve_sync.source_executor import SourceExecutorDispatch

from tests.sample_data import sample_source_config


def source(source_id, source_type='proxmox'):
    """Build a distinct immutable source for orchestration tests."""

    return replace(
        sample_source_config(address=f'{source_id}.test.example'),
        id=source_id,
        source_instance=source_id,
        source_type=source_type,
    )


def test_two_sources_execute_deterministically_with_isolated_instances():
    seen = []
    dispatch = SourceExecutorDispatch({
        'proxmox': lambda config: seen.append(
            (config.id, config.source_instance)
        ),
    })

    result = run_sources(
        (source('pve-b'), source('pve-a')),
        dispatch.execute,
    )

    assert seen == [('pve-a', 'pve-a'), ('pve-b', 'pve-b')]
    assert [item.source_instance for item in result.results] == [
        'pve-a', 'pve-b',
    ]
    assert (result.total, result.succeeded, result.failed) == (2, 2, 0)
    assert result.skipped == 0


def test_first_source_failure_does_not_stop_second():
    seen = []

    def execute(config):
        seen.append(config.id)
        if config.id == 'pve-a':
            raise RuntimeError('first failed')

    result = run_sources((source('pve-a'), source('pve-b')), execute)

    assert seen == ['pve-a', 'pve-b']
    assert [item.success for item in result.results] == [False, True]
    assert (result.succeeded, result.failed) == (1, 1)


def test_second_source_failure_is_reported_separately():
    def execute(config):
        if config.id == 'pve-b':
            raise ValueError('second failed')

    result = run_sources((source('pve-a'), source('pve-b')), execute)

    assert result.results[0].success is True
    assert result.results[1].success is False
    assert result.results[1].error_type == 'ValueError'
    assert result.results[1].error_summary == 'source execution failed'


def test_system_exit_from_one_source_is_isolated():
    seen = []

    def execute(config):
        seen.append(config.id)
        if config.id == 'pve-a':
            raise SystemExit(2)

    result = run_sources((source('pve-a'), source('pve-b')), execute)

    assert seen == ['pve-a', 'pve-b']
    assert result.failed == 1
    assert result.results[0].error_type == 'SystemExit'


def test_unknown_source_type_fails_only_that_source():
    seen = []
    dispatch = SourceExecutorDispatch({
        'proxmox': lambda config: seen.append(config.id),
    })

    result = run_sources(
        (source('future-source', 'esxi'), source('pve-b')),
        dispatch.execute,
    )

    assert seen == ['pve-b']
    assert result.results[0].source_id == 'future-source'
    assert result.results[0].success is False
    assert result.results[0].error_type == 'UnsupportedSourceTypeError'
    assert result.results[1].success is True


def test_run_result_never_contains_exception_or_secret_text():
    secret = 'FAKE_ORCHESTRATOR_SECRET_MUST_NOT_APPEAR'

    def fail(_config):
        raise RuntimeError(f'credential was {secret}')

    result = run_sources((source('pve-a'),), fail)

    assert secret not in repr(result)
    assert 'credential was' not in repr(result)
    assert result.results[0].error_type == 'RuntimeError'
    assert result.results[0].started_at.tzinfo is not None
    assert result.results[0].finished_at.tzinfo is not None
