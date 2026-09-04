"""WEB-5B confirmation, stale-plan, and eligibility safety."""

from dataclasses import replace

import pytest

from netbox_pve_sync.application.confirmation import ConfirmationStore
from netbox_pve_sync.application.discovery_review import (DiscoveryReview, ReviewClassification,
                                                            ReviewItem)
from netbox_pve_sync.application.manual_sync import ManualSyncError, ManualSyncService
from netbox_pve_sync.application.sync_plan import plan_from_review
from tests.sample_data import sample_source_config


class Clock:
    value = 1.0

    def __call__(self):
        return self.value


def make_plan(source, classification=ReviewClassification.MANAGED, marker='1'):
    review = DiscoveryReview(source.source_instance, source.source_type, source.target.site_slug,
                             source.target.cluster_name, (ReviewItem(
                                 'qemu', 'vm', marker, classification, 'TEST', 'test', 'none', 1, 'vm'),))
    return plan_from_review(review, source)


def service(source, *, clock=None, writes=None, planner=None):
    writes = [] if writes is None else writes
    store = ConfirmationStore(ttl_seconds=5, clock=clock or Clock())
    return ManualSyncService(lambda instance: source if instance == source.source_instance else None,
                             planner or make_plan, lambda config, plan: writes.append((config, plan)),
                             store), writes


def test_token_is_single_use_and_source_bound():
    source = sample_source_config()
    sync, writes = service(source)
    token = sync.prepare(source.source_instance, make_plan(source).digest)
    sync.apply(source.source_instance, token)
    assert len(writes) == 1
    with pytest.raises(ManualSyncError, match='CONFIRMATION_INVALID'):
        sync.apply(source.source_instance, token)


def test_expired_token_and_cross_source_are_rejected_without_write():
    source = sample_source_config()
    clock = Clock()
    sync, writes = service(source, clock=clock)
    token = sync.prepare(source.source_instance, make_plan(source).digest)
    with pytest.raises(ManualSyncError, match='CONFIRMATION_SOURCE_MISMATCH'):
        sync.apply('different-source', token)
    token = sync.prepare(source.source_instance, make_plan(source).digest)
    clock.value = 7
    with pytest.raises(ManualSyncError, match='CONFIRMATION_EXPIRED'):
        sync.apply(source.source_instance, token)
    assert writes == []


def test_plan_is_recomputed_and_stale_digest_prevents_write():
    source = sample_source_config()
    state = {'marker': '1', 'calls': 0}
    def planner(config):
        state['calls'] += 1
        return make_plan(config, marker=state['marker'])
    sync, writes = service(source, planner=planner)
    token = sync.prepare(source.source_instance, planner(source).digest)
    state['marker'] = '2'
    with pytest.raises(ManualSyncError, match='PLAN_STALE'):
        sync.apply(source.source_instance, token)
    assert state['calls'] >= 3
    assert writes == []


def test_blocked_plan_and_disabled_source_fail_before_write():
    source = sample_source_config()
    blocked = lambda config: make_plan(config, ReviewClassification.CONFLICT)
    sync, writes = service(source, planner=blocked)
    with pytest.raises(ManualSyncError, match='PLAN_BLOCKED'):
        sync.prepare(source.source_instance, blocked(source).digest)
    disabled = replace(source, enabled=False)
    sync, _ = service(disabled)
    with pytest.raises(ManualSyncError, match='SOURCE_DISABLED'):
        sync.prepare(disabled.source_instance, make_plan(disabled).digest)
    assert writes == []


def test_sync_disabled_source_is_manually_eligible_and_flags_are_unchanged():
    source = replace(sample_source_config(), sync_enabled=False)
    sync, writes = service(source)
    token = sync.prepare(source.source_instance, make_plan(source).digest)
    sync.apply(source.source_instance, token)
    assert writes[0][0].enabled is True
    assert writes[0][0].sync_enabled is False


def test_review_required_is_excluded_but_does_not_block_safe_work():
    source = sample_source_config()
    planner = lambda config: make_plan(config, ReviewClassification.REVIEW_REQUIRED)
    sync, writes = service(source, planner=planner)
    token = sync.prepare(source.source_instance, planner(source).digest)
    sync.apply(source.source_instance, token)
    assert len(writes) == 1
