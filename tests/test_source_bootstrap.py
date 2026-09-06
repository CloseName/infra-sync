"""Safety and idempotency tests for legacy-to-registry bootstrap."""

from dataclasses import dataclass, replace

import pytest

from netbox_sync.source_bootstrap import (
    SourceBootstrapError,
    bootstrap_legacy_source,
)

from tests.sample_data import sample_source_config


@dataclass(frozen=True)
class FakeRecord:
    """In-memory equivalent of the registry's persisted record."""

    config: object

    @property
    def id(self):
        return self.config.id


class FakeRegistry:
    """Atomic in-memory SourceRegistry test double with write accounting."""

    def __init__(self, configs=(), fail_update=False):
        self.records = {
            config.id: FakeRecord(config)
            for config in configs
        }
        self.creates = 0
        self.updates = 0
        self.fail_update = fail_update

    def get_source(self, source_id):
        return self.records.get(source_id)

    def get_by_source_instance(self, source_instance):
        return next(
            (
                record
                for record in self.records.values()
                if record.config.source_instance == source_instance
            ),
            None,
        )

    def create_source(self, config):
        self.creates += 1
        record = FakeRecord(config)
        self.records[config.id] = record
        return record

    def update_source(self, source_id, **changes):
        if self.fail_update:
            raise RuntimeError('simulated transactional failure')
        self.updates += 1
        record = FakeRecord(replace(self.records[source_id].config, **changes))
        self.records[source_id] = record
        return record


def test_legacy_source_dry_run_is_create_candidate_with_zero_writes():
    registry = FakeRegistry()

    result = bootstrap_legacy_source(registry, sample_source_config())

    assert result.action == 'create'
    assert (result.created, result.updated, result.noop) == (1, 0, 0)
    assert result.confirmed is False
    assert registry.creates == 0
    assert registry.updates == 0
    assert registry.records == {}


def test_non_boolean_confirmation_fails_closed():
    registry = FakeRegistry()

    with pytest.raises(TypeError, match='boolean'):
        bootstrap_legacy_source(
            registry,
            sample_source_config(),
            confirmed='REGISTRY_WRITE',
        )

    assert registry.creates == 0


def test_confirmed_create_then_repeat_is_idempotent():
    registry = FakeRegistry()
    config = sample_source_config()

    created = bootstrap_legacy_source(registry, config, confirmed=True)
    repeated = bootstrap_legacy_source(registry, config, confirmed=True)

    assert created.action == 'create'
    assert repeated.action == 'noop'
    assert (repeated.created, repeated.updated, repeated.noop) == (0, 0, 1)
    assert registry.creates == 1
    assert registry.updates == 0
    credentials = registry.records[config.id].config.credentials
    assert credentials.token_id.provider == 'file'
    assert credentials.token_id.key == 'proxmox_token_id'


def test_mutable_difference_requires_confirmation_then_becomes_noop():
    desired = sample_source_config(address='new-pve.test.example')
    existing = replace(desired, address='old-pve.test.example')
    registry = FakeRegistry((existing,))

    dry_run = bootstrap_legacy_source(registry, desired)

    assert dry_run.action == 'update'
    assert [change.field for change in dry_run.changes] == ['address', 'credentials']
    assert registry.records[desired.id].config.address == 'old-pve.test.example'
    assert registry.updates == 0

    applied = bootstrap_legacy_source(registry, desired, confirmed=True)
    repeated = bootstrap_legacy_source(registry, desired)

    assert applied.updated == 1
    assert repeated.noop == 1
    assert registry.updates == 1
    assert registry.records[desired.id].config.address == 'new-pve.test.example'


@pytest.mark.parametrize(
    'existing',
    (
        replace(sample_source_config(), source_instance='pve-other'),
        replace(sample_source_config(), id='other-id'),
        replace(sample_source_config(), source_type='other'),
    ),
)
def test_immutable_identity_conflicts_fail_closed(existing):
    registry = FakeRegistry((existing,))
    before = dict(registry.records)

    with pytest.raises(SourceBootstrapError, match='conflict'):
        bootstrap_legacy_source(registry, sample_source_config(), confirmed=True)

    assert registry.records == before
    assert registry.creates == 0
    assert registry.updates == 0


def test_duplicate_source_instance_selecting_another_id_fails_closed():
    existing = replace(sample_source_config(), id='existing-other-id')
    registry = FakeRegistry((existing,))

    with pytest.raises(SourceBootstrapError, match='immutable id'):
        bootstrap_legacy_source(registry, sample_source_config(), confirmed=True)

    assert registry.creates == 0
    assert registry.updates == 0


def test_diff_is_deterministic_and_never_contains_plaintext_secret():
    secret_value = 'FAKE_BOOTSTRAP_SECRET_MUST_NOT_APPEAR'
    existing = replace(
        sample_source_config(),
        settings={'z': 1, 'nested': {'api_token': 'old-secret'}, 'a': 2},
    )
    desired = replace(
        sample_source_config(),
        settings={'a': 3, 'nested': {'api_token': secret_value}, 'z': 1},
    )
    registry = FakeRegistry((existing,))

    first = bootstrap_legacy_source(registry, desired)
    second = bootstrap_legacy_source(registry, desired)
    rendered = repr(first.changes)

    assert first.changes == second.changes
    assert secret_value not in rendered
    assert 'old-secret' not in rendered
    assert '<redacted>' in rendered
    assert 'file:proxmox_token_secret' in rendered
    assert registry.updates == 0


def test_transaction_failure_leaves_existing_source_unchanged():
    existing = sample_source_config(address='old-pve.test.example')
    desired = sample_source_config(address='new-pve.test.example')
    registry = FakeRegistry((existing,), fail_update=True)

    with pytest.raises(RuntimeError, match='transactional failure'):
        bootstrap_legacy_source(registry, desired, confirmed=True)

    assert registry.records[existing.id].config == existing
    assert registry.creates == 0
    assert registry.updates == 0
