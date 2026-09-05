"""Run history domain mapping remains closed and secret-free."""

import pytest

from netbox_pve_sync.run_history import (ActionCounts, RunStatus, postgres_run_repository,
                                         safe_error_code, safe_error_message, terminal_status)


def test_action_counts_use_only_canonical_actions():
    counts = ActionCounts.from_items([
        {'action': 'CREATE'}, {'action': 'CREATE'}, {'action': 'UPDATE'},
        {'action': 'NO_CHANGE'}, {'action': 'UNKNOWN'},
    ])
    assert (counts.create, counts.update, counts.no_change) == (2, 1, 1)
    assert counts.review_required == counts.blocked == 0


def test_stable_errors_map_to_closed_status_and_safe_text():
    assert terminal_status('APPLY_LOCKED') is RunStatus.LOCKED
    assert terminal_status('PLAN_STALE') is RunStatus.FAILED
    assert terminal_status('OUTCOME_UNCERTAIN') is RunStatus.OUTCOME_UNCERTAIN
    assert safe_error_message('unknown password=secret') == 'Synchronization failed.'
    assert safe_error_code('unknown password=secret') == 'APPLY_FAILED'


def test_apply_runtime_requires_run_writer_configuration():
    with pytest.raises(RuntimeError, match='history writer configuration'):
        postgres_run_repository('', 'infra_sync')
