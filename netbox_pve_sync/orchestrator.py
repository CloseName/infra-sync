"""Source-agnostic, sequential multi-source orchestration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .source_config import SourceConfig
from .run_history import (ActionCounts, RunStatus, RunTrigger, safe_error_code,
                          safe_error_message, terminal_status)


@dataclass(frozen=True)
class SourceRunResult:
    """Secret-safe outcome for one attempted source."""

    source_id: str
    source_instance: str
    source_type: str
    success: bool
    started_at: datetime
    finished_at: datetime
    error_type: Optional[str] = None
    error_summary: Optional[str] = None


@dataclass(frozen=True)
class MultiSourceRunResult:
    """Aggregate result for a deterministic multi-source execution."""

    results: tuple[SourceRunResult, ...]

    @property
    def total(self):
        """Return attempted source count."""

        return len(self.results)

    @property
    def succeeded(self):
        """Return successful source count."""

        return sum(result.success for result in self.results)

    @property
    def failed(self):
        """Return failed source count."""

        return self.total - self.succeeded

    @property
    def skipped(self):
        """No selected source is skipped by this phase's orchestrator."""

        return 0


def _utc_now():
    return datetime.now(timezone.utc)


def run_sources(sources, execute_source, clock=None, run_repository=None):
    """Execute immutable configs sequentially and isolate per-source failures."""

    now = clock or _utc_now
    configs = tuple(sources)
    for config in configs:
        if not isinstance(config, SourceConfig):
            raise TypeError('sources must contain only SourceConfig objects')

    results = []
    for source in sorted(configs, key=lambda config: config.id):
        started_at = now()
        run = run_repository.start_run(
            source.source_instance, source.source_type, RunTrigger.SCHEDULED,
            'system/scheduler',
        ) if run_repository else None
        try:
            execution = execute_source(source)
        except (Exception, SystemExit) as exc:  # pylint: disable=broad-exception-caught
            code = safe_error_code(getattr(exc, 'code', None))
            if run:
                run_repository.finish_run(
                    run.run_id, terminal_status(code), error_code=code,
                    error_message_safe=safe_error_message(code),
                )
            results.append(
                SourceRunResult(
                    source_id=source.id,
                    source_instance=source.source_instance,
                    source_type=source.source_type,
                    success=False,
                    started_at=started_at,
                    finished_at=now(),
                    error_type=type(exc).__name__,
                    error_summary='source execution failed',
                )
            )
            continue
        if run:
            run_repository.finish_run(
                run.run_id, RunStatus.SUCCEEDED,
                counts=ActionCounts.from_items(getattr(execution, 'items', ())),
                plan_digest=getattr(execution, 'digest', None),
                planner_version=getattr(execution, 'planner_version', None),
            )
        results.append(
            SourceRunResult(
                source_id=source.id,
                source_instance=source.source_instance,
                source_type=source.source_type,
                success=True,
                started_at=started_at,
                finished_at=now(),
            )
        )
    return MultiSourceRunResult(results=tuple(results))
