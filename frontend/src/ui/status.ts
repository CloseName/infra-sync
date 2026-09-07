export type Tone = "success" | "warning" | "danger" | "neutral" | "info";
export interface Status {
  label: string;
  tone: Tone;
  icon: string;
}
const state = (label: string, tone: Tone, icon: string): Status => ({
  label,
  tone,
  icon,
});
export const health = {
  HEALTHY: state("Healthy", "success", "✓"),
  DEGRADED: state("Needs attention", "warning", "!"),
  UNHEALTHY: state("Unhealthy", "danger", "!"),
  UNAVAILABLE: state("Unavailable", "neutral", "?"),
  UNKNOWN: state("Not verified", "neutral", "?"),
} as const;
export const scheduleStates = {
  DISABLED: state("Automatic sync off", "neutral", "−"),
  WAITING: state("Waiting", "neutral", "◷"),
  DUE: state("Due", "info", "◷"),
  RUNNING: state("Running", "info", "↻"),
  DELAYED: state("Later than expected", "warning", "!"),
} as const;
export const runStates = {
  RUNNING: state("Recorded as running", "info", "↻"),
  SUCCEEDED: state("Completed", "success", "✓"),
  FAILED_BEFORE_WRITE: state("Failed before changes", "danger", "!"),
  PARTIALLY_APPLIED: state("Partially applied", "warning", "!"),
  OUTCOME_UNCERTAIN: state("Outcome unknown", "danger", "?"),
  BLOCKED: state("Blocked by safety checks", "danger", "!"),
  LOCKED: state("Not started — sync busy", "warning", "◷"),
  FAILED: state("Failed", "danger", "!"),
} as const;
export const staleStatus = state("Completion unconfirmed", "warning", "?");
export function healthStatus(value?: string): Status {
  return (
    health[value?.toUpperCase() as keyof typeof health] ?? health.UNAVAILABLE
  );
}
export function runStatus(value: string, stale = false): Status {
  return stale
    ? staleStatus
    : (runStates[value as keyof typeof runStates] ??
        state("Unknown outcome", "neutral", "?"));
}
