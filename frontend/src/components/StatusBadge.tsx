import type { HealthStatus } from '../types/health';

export function StatusBadge({ status }: { status: HealthStatus }) {
  return <span className={`status status-${status}`}><span aria-hidden="true">●</span> {status}</span>;
}
