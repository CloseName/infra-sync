import type { Diagnostics, DiagnosticComponent } from "../api/diagnostics";
import { diagnosticsUsable } from "./operations.ts";
export const componentLabels = {
  api: "API",
  registry: "Registry",
  run_history: "Run history",
  discovery_worker: "Discovery worker",
  apply_worker: "Apply worker",
  scheduler: "Scheduled activity",
} as const;
export type ComponentKey = keyof typeof componentLabels;
export function componentReason(
  key: ComponentKey,
  c: DiagnosticComponent,
): string {
  if (c.status === "UNKNOWN")
    return c.safe_message || "No verification evidence is available.";
  if (c.status !== "HEALTHY")
    return c.safe_message || "This check needs attention.";
  if (key === "scheduler")
    return "Scheduled runs are recorded. This is activity evidence, not a live heartbeat.";
  if (key === "api") return "API responded to this diagnostic request.";
  if (key === "registry") return "Source registry read succeeded.";
  if (key === "run_history") return "Run history read succeeded.";
  return "Worker health check responded. Provider and NetBox connectivity are not tested here.";
}
export function aggregateReason(data: Diagnostics): string {
  const checked = Object.entries(data.components).filter(
    ([key]) => key !== "scheduler",
  );
  const available = checked.every(([, c]) => c.status === "HEALTHY");
  const staleOnly =
    data.overall_status === "DEGRADED" &&
    available &&
    data.stale_runs.length > 0 &&
    data.warnings.every((w) => w.warning_code === "STALE_RUNNING") &&
    data.sources.every((s) =>
      ["SUCCEEDED", "RUNNING", undefined].includes(s.latest_run?.status),
    ) &&
    ["HEALTHY", "UNKNOWN"].includes(data.components.scheduler.status);
  if (staleOnly)
    return "Checked components are available. Historical run completion is unconfirmed in the returned evidence.";
  if (data.overall_status === "UNHEALTHY")
    return "Source or registry evidence requires investigation. Review the affected entries below.";
  if (data.overall_status === "DEGRADED")
    return "Component or recorded activity evidence needs attention. Review the affected entries below.";
  return "No aggregate fault reported in this snapshot. Unverified checks and source connectivity remain separate.";
}
export function coverage(data: Diagnostics): string {
  if (!diagnosticsUsable(data))
    return "Source assessment is incomplete because registry or run history evidence is unavailable.";
  return data.stale_runs.length >= 100
    ? "The 100 oldest stale runs are shown; more may exist. This snapshot is not a complete issue count."
    : "Stale evidence covers up to 100 oldest runs; source outcomes reflect their latest recorded runs. This is not a complete issue count.";
}
