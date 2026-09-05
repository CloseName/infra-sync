"""Fixed-tick registry scheduler using persisted scheduled history."""

from dataclasses import dataclass
from datetime import datetime, timezone

from .application.scheduling import evaluate_schedule
from .orchestrator import MultiSourceRunResult, run_sources


@dataclass(frozen=True)
class SchedulerTickResult:
    """Bounded decisions and existing execution outcomes for one tick."""

    decisions: tuple
    execution: MultiSourceRunResult

    @property
    def counts(self):
        result = {name: 0 for name in ('disabled', 'waiting', 'due', 'running', 'delayed')}
        for decision in self.decisions:
            result[decision.state.value.lower()] += 1
        return result


def run_scheduler_tick(sources, execute_source, run_repository, stale_seconds=7200, clock=None,
                       execute_due=True):
    """Evaluate every source once and execute eligible sources sequentially once."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    configs = tuple(sorted(tuple(sources), key=lambda item: item.id))
    latest = {run.source_instance: run for run in
              run_repository.latest_by_source(trigger='scheduled')}
    running = {run.source_instance: run for run in
               run_repository.latest_by_source(trigger='scheduled', status='RUNNING')}
    decisions = tuple(evaluate_schedule(
        source, latest.get(source.source_instance), running.get(source.source_instance),
        now, stale_seconds,
    ) for source in configs)
    eligible = tuple(source for source, decision in zip(configs, decisions)
                     if decision.eligible)
    execution = run_sources(eligible if execute_due else (), execute_source, clock=clock,
                            run_repository=run_repository if execute_due else None)
    return SchedulerTickResult(decisions, execution)
