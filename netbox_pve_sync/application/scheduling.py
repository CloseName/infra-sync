"""Deterministic derived per-source scheduling policy."""

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum


MIN_SYNC_INTERVAL = 60
MAX_SYNC_INTERVAL = 86400


def stale_threshold(value=7200):
    """Return the shared bounded WEB-7/WEB-8 stale threshold."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 7200
    return parsed if 300 <= parsed <= 604800 else 7200


class SchedulerState(str, Enum):
    """Closed source scheduling states."""

    DISABLED = 'DISABLED'
    WAITING = 'WAITING'
    DUE = 'DUE'
    RUNNING = 'RUNNING'
    DELAYED = 'DELAYED'


@dataclass(frozen=True)
class ScheduleDecision:
    """One read-only decision derived from config and scheduled history."""

    source_instance: str
    state: SchedulerState
    last_scheduled_run_at: object | None
    next_expected_at: object | None

    @property
    def eligible(self):
        return self.state in (SchedulerState.DUE, SchedulerState.DELAYED)


def validate_interval(value, *, current=False):
    """Validate desired intervals, allowing legacy positive values only as expectations."""
    maximum = 2147483647 if current else MAX_SYNC_INTERVAL
    if (not isinstance(value, int) or isinstance(value, bool)
            or not (1 if current else MIN_SYNC_INTERVAL) <= value <= maximum):
        raise ValueError('invalid synchronization interval')
    return value


def evaluate_schedule(source, latest_scheduled, latest_running, now, stale_seconds):
    """Apply the single cadence policy shared by runtime and diagnostics."""
    reference = latest_scheduled.started_at if latest_scheduled else None
    if not source.enabled or not source.sync_enabled:
        return ScheduleDecision(source.source_instance, SchedulerState.DISABLED, reference, None)
    next_expected = (reference + timedelta(seconds=source.sync_interval_seconds)
                     if reference else now)
    if (latest_running is not None
            and (now - latest_running.started_at).total_seconds() <= stale_seconds):
        return ScheduleDecision(source.source_instance, SchedulerState.RUNNING,
                                reference, next_expected)
    if now < next_expected:
        state = SchedulerState.WAITING
    elif reference is None or now == next_expected:
        state = SchedulerState.DUE
    else:
        delayed_after = max(source.sync_interval_seconds * 2, 1800)
        state = (SchedulerState.DELAYED
                 if (now - reference).total_seconds() > delayed_after
                 else SchedulerState.DUE)
    return ScheduleDecision(source.source_instance, state, reference, next_expected)
