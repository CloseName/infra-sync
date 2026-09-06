import type { HealthStatus } from '../types/health';
import { Badge } from '../ui/primitives';
import { healthStatus } from '../ui/status';
export function StatusBadge({ status }: { status: HealthStatus }) {
  return <Badge value={healthStatus(status)} code={status} />;
}
