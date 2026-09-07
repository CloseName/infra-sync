import assert from "node:assert/strict";
import test from "node:test";
import { fetchDiagnostics, isDiagnostics } from "../src/api/diagnostics.ts";

const component = {
  status: "HEALTHY",
  checked_at: "2026-09-05T12:00:00Z",
  safe_code: null,
  safe_message: null,
  last_seen_at: "2026-09-05T12:00:00Z",
  last_success_at: null,
  next_expected_at: null,
};
const run = {
  run_id: "11111111-1111-4111-8111-111111111111",
  trigger: "scheduled",
  status: "SUCCEEDED",
  started_at: "2026-09-05T11:00:00Z",
  finished_at: "2026-09-05T11:01:00Z",
};
const source = {
  source_instance: "pve-test",
  source_type: "proxmox",
  enabled: true,
  sync_enabled: true,
  sync_interval_seconds: 600,
  status: "HEALTHY",
  latest_run: run,
  latest_success_at: run.started_at,
  latest_scheduled_run: run,
  latest_manual_run: null,
  scheduler_state: "WAITING",
  last_scheduled_run_at: run.started_at,
  next_expected_at: "2026-09-05T11:10:00Z",
  warning_count: 0,
  warnings: [],
};
const diagnostics = {
  overall_status: "HEALTHY",
  generated_at: "2026-09-05T12:00:00Z",
  components: Object.fromEntries(
    [
      "api",
      "registry",
      "run_history",
      "discovery_worker",
      "apply_worker",
      "scheduler",
    ].map((name) => [name, component]),
  ),
  sources: [source],
  stale_runs: [],
  warnings: [],
};

test("diagnostics client accepts healthy degraded and unhealthy closed states", () => {
  for (const status of ["HEALTHY", "DEGRADED", "UNHEALTHY"])
    assert.equal(
      isDiagnostics({ ...diagnostics, overall_status: status }),
      true,
    );
  assert.equal(
    isDiagnostics({ ...diagnostics, overall_status: ["HEALTHY"] }),
    false,
  );
});

test("diagnostics client validates component, source, and stale warning states", () => {
  for (const status of ["HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"])
    assert.equal(
      isDiagnostics({
        ...diagnostics,
        components: {
          ...diagnostics.components,
          apply_worker: { ...component, status },
        },
      }),
      true,
    );
  const stale = {
    warning_code: "STALE_RUNNING",
    safe_message:
      "Synchronization run has remained RUNNING longer than expected.",
    source_instance: "esxi-test",
    source_type: "esxi",
    trigger: "scheduled",
    run_id: run.run_id,
    started_at: run.started_at,
    age_seconds: 7201,
  };
  assert.equal(
    isDiagnostics({ ...diagnostics, stale_runs: [stale], warnings: [stale] }),
    true,
  );
  assert.equal(
    isDiagnostics({
      ...diagnostics,
      stale_runs: [{ ...stale, trigger: ["scheduled"] }],
    }),
    false,
  );
});

test("diagnostics client rejects malformed DTO and hides raw backend errors", async (context) => {
  const mock = context.mock.method(globalThis, "fetch", async () =>
    Response.json({
      ...diagnostics,
      components: {
        ...diagnostics.components,
        apply_worker: { ...component, status: ["HEALTHY"] },
      },
    }),
  );
  await assert.rejects(
    fetchDiagnostics(new AbortController().signal),
    /Diagnostics unavailable/,
  );
  mock.mock.mockImplementation(
    async () =>
      new Response("password=secret raw socket path", { status: 503 }),
  );
  await assert.rejects(
    fetchDiagnostics(new AbortController().signal),
    (error) => error.message === "Diagnostics unavailable.",
  );
});
