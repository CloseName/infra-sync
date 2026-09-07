import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Source } from "../api/sources";
import { runDiscovery } from "../api/discovery";
import type { DiscoveryResult } from "../api/discovery";
import {
  applySync,
  buildSyncPlan,
  ManualSyncRequestError,
  prepareSync,
} from "../api/sync";
import type { SyncPlan } from "../api/sync";
import { applyOutcome, failedOutcome } from "../ui/syncOutcome";
import type { SyncOutcome } from "../ui/syncOutcome";
import { Badge, Timestamp } from "../ui/primitives";
import { sourcePath, runPath } from "../ui/routes";
import { PlanReview, PlanSummary } from "../components/PlanReview";
import { DiscoveryReview } from "../components/DiscoveryReview";
type Phase = "idle" | "planning" | "validating" | "applying";
function Elapsed({ start }: { start: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <span aria-live="off">
      Elapsed {Math.max(0, Math.floor((now - start) / 1000))} s
    </span>
  );
}
export function SourceSync({
  detail,
  active = true,
}: {
  detail: Source;
  active?: boolean;
}) {
  const [phase, setPhase] = useState<Phase>("idle"),
    [started, setStarted] = useState(0);
  const [plan, setPlan] = useState<{
      value: SyncPlan;
      received: string;
    } | null>(null),
    [usable, setUsable] = useState(false);
  const [planningError, setPlanningError] =
    useState<ManualSyncRequestError | null>(null);
  const [result, setResult] = useState<SyncOutcome | null>(null);
  const [discovery, setDiscovery] = useState<{
    value: DiscoveryResult;
    received: string;
  } | null>(null);
  const [discovering, setDiscovering] = useState(false),
    [discoveryStarted, setDiscoveryStarted] = useState(0),
    [discoveryError, setDiscoveryError] = useState("");
  const [discoveryOpen, setDiscoveryOpen] = useState(false),
    [confirmOpen, setConfirmOpen] = useState(false);
  const busy = useRef(false),
    discoveryBusy = useRef(false),
    alive = useRef(true);
  const dialog = useRef<HTMLDialogElement>(null),
    confirmButton = useRef<HTMLButtonElement>(null),
    cancelButton = useRef<HTMLButtonElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  const selected = detail.source_instance;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const element = dialog.current;
    if (confirmOpen && active && !element?.open) {
      element?.showModal();
      cancelButton.current?.focus();
    }
    if ((!confirmOpen || !active) && element?.open) element.close();
    if (!active) setConfirmOpen(false);
  }, [confirmOpen, active]);
  useEffect(() => {
    if (active && (result || planningError) && feedback.current?.offsetParent)
      feedback.current.focus();
  }, [result, planningError, active]);
  const closeDialog = () => {
    setConfirmOpen(false);
    dialog.current?.close();
    if (active) confirmButton.current?.focus();
  };
  const buildPlan = async () => {
    if (busy.current || !detail.enabled) return;
    busy.current = true;
    setPhase("planning");
    setStarted(Date.now());
    setUsable(false);
    setPlanningError(null);
    try {
      const value = await buildSyncPlan(selected, AbortSignal.timeout(330000));
      if (alive.current) {
        setPlan({ value, received: new Date().toISOString() });
        setUsable(true);
      }
    } catch (error) {
      if (alive.current)
        setPlanningError(
          error instanceof ManualSyncRequestError
            ? error
            : new ManualSyncRequestError("Plan could not be built."),
        );
    } finally {
      busy.current = false;
      if (alive.current) setPhase("idle");
    }
  };
  const discover = async () => {
    if (discoveryBusy.current || !detail.enabled || busy.current) return;
    discoveryBusy.current = true;
    setDiscovering(true);
    setDiscoveryOpen(true);
    setDiscoveryStarted(Date.now());
    setDiscoveryError("");
    try {
      const value = await runDiscovery(selected, AbortSignal.timeout(330000));
      if (alive.current)
        setDiscovery({ value, received: new Date().toISOString() });
    } catch (error) {
      if (alive.current)
        setDiscoveryError(
          error instanceof Error ? error.message : "Discovery failed.",
        );
    } finally {
      discoveryBusy.current = false;
      if (alive.current) setDiscovering(false);
    }
  };
  const submit = async () => {
    if (
      !active ||
      busy.current ||
      !confirmOpen ||
      !plan ||
      !usable ||
      !plan.value.apply_allowed ||
      !detail.enabled
    )
      return;
    const reviewed = plan.value;
    busy.current = true;
    setPhase("validating");
    setStarted(Date.now());
    setUsable(false);
    let stage: "validating" | "applying" = "validating";
    try {
      const token = await prepareSync(
        selected,
        reviewed.digest,
        AbortSignal.timeout(330000),
      );
      // Navigation to another source must not cause a later prepare response to submit apply.
      if (!alive.current) return;
      stage = "applying";
      setPhase("applying");
      const value = await applySync(
        selected,
        token,
        AbortSignal.timeout(330000),
      );
      if (alive.current) setResult(applyOutcome(value, reviewed.digest));
    } catch (error) {
      if (alive.current) setResult(failedOutcome(error, stage));
    } finally {
      busy.current = false;
      if (alive.current) {
        setPhase("idle");
        setConfirmOpen(false);
        dialog.current?.close();
      }
    }
  };
  const applying = phase === "validating" || phase === "applying";
  return (
    <section className="sync-workspace" aria-labelledby="sync-title">
      <h2 id="sync-title">Sync</h2>
      <p>Build plan → Review → Confirm Sync → Result</p>
      <p className="muted">
        {detail.name} → Site {detail.site_slug} / {detail.cluster_name}
      </p>
      <div className="page-actions">
        <button
          className="primary"
          disabled={phase !== "idle" || confirmOpen || !detail.enabled}
          onClick={buildPlan}
        >
          {plan ? "Rebuild plan" : "Build plan"}
        </button>
        <button
          disabled={
            phase !== "idle" || discovering || confirmOpen || !detail.enabled
          }
          onClick={discover}
        >
          Run discovery
        </button>
      </div>
      {!detail.enabled && (
        <p className="sync-attention">
          Source disabled. Planning, discovery and manual sync are unavailable
          for this source.
        </p>
      )}
      {phase !== "idle" && (
        <div className="sync-pending">
          <p role="status">
            {phase === "planning"
              ? "Building read-only plan"
              : phase === "validating"
                ? "Preparing / validating reviewed plan"
                : "Submitting / applying reviewed plan"}{" "}
            for {detail.name}.
          </p>
          <Elapsed start={started} />
        </div>
      )}
      <div ref={feedback} tabIndex={-1}>
        {planningError && (
          <div className="source-error" role="alert">
            <strong>Plan could not be built.</strong>
            <p>{planningError.message}</p>
            <details>
              <summary>Safe technical details</summary>
              <code>{planningError.code}</code>
            </details>
            <p>
              This was a read-only planning request. Build a new plan to try
              planning again.
            </p>
          </div>
        )}
        {result && (
          <section
            className={
              "sync-result " +
              (["PARTIALLY_APPLIED", "OUTCOME_UNCERTAIN"].includes(result.state)
                ? "sync-attention"
                : "source-panel")
            }
            role={result.state === "SUCCEEDED" ? "status" : "alert"}
            aria-label="Sync result"
          >
            <h3>
              <Badge value={result.status} />
            </h3>
            <p>{result.message}</p>
            {["FAILED", "OUTCOME_UNCERTAIN", "PARTIALLY_APPLIED"].includes(
              result.state,
            ) && (
              <p>
                No automatic retry. Review recorded history and source
                diagnostics before continuing.
              </p>
            )}
            <div className="page-actions">
              {result.runId && (
                <Link className="button" to={runPath(result.runId)}>
                  Open run
                </Link>
              )}
              <Link to={sourcePath(selected) + "/runs"}>
                Source run history
              </Link>
              <Link to={sourcePath(selected) + "/diagnostics"}>
                Source diagnostics
              </Link>
            </div>
            {result.code && (
              <details>
                <summary>Safe technical details</summary>
                <code>{result.code}</code>
              </details>
            )}
          </section>
        )}
      </div>
      {!plan && phase !== "planning" && !planningError && (
        <div className="source-panel">
          <h3>No plan yet</h3>
          <p>
            Build a read-only plan of managed operations before syncing.
            Discovery is optional and is not a prerequisite for Build plan.
          </p>
        </div>
      )}
      {usable && phase === "idle" && (
        <p role="status">Plan ready for review.</p>
      )}
      {plan && (
        <PlanReview
          key={plan.received}
          plan={plan.value}
          received={plan.received}
          previous={!usable}
        />
      )}
      {plan && (
        <div className="sync-action-bar">
          <p>
            Missing objects are retained in NetBox. No deletes. Only the
            reviewed canonical plan is submitted.
          </p>
          <button
            ref={confirmButton}
            className="primary"
            disabled={
              phase !== "idle" ||
              !usable ||
              !plan.value.apply_allowed ||
              !detail.enabled
            }
            onClick={() => setConfirmOpen(true)}
          >
            Review and confirm sync
          </button>
        </div>
      )}
      <details
        className="source-panel discovery-tool"
        open={discoveryOpen}
        onToggle={(e) => setDiscoveryOpen(e.currentTarget.open)}
      >
        <summary>Discovery · optional read-only inspection</summary>
        <p>
          Inspect discovered objects and how they match NetBox. No NetBox
          changes are made.
        </p>
        {discovering && (
          <div className="sync-pending">
            <p role="status">Discovering source {detail.name}…</p>
            <Elapsed start={discoveryStarted} />
          </div>
        )}
        {discoveryError && (
          <p role="alert" className="source-error">
            {discoveryError}
          </p>
        )}
        {discovery && (
          <DiscoveryReview
            result={discovery.value}
            received={discovery.received}
            previous={discovering}
          />
        )}
        {!discovery && !discovering && (
          <p>
            Run discovery to inspect matching and classification evidence
            independently of planning.
          </p>
        )}
      </details>
      <dialog
        ref={dialog}
        className="sync-dialog"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ),
          );
          const first = controls[0],
            last = controls.at(-1);
          if (!first) {
            event.preventDefault();
            return;
          }
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        onCancel={(e) => {
          e.preventDefault();
          if (!applying) closeDialog();
        }}
      >
        <h2 id="confirm-title">Sync changes to NetBox</h2>
        <p id="confirm-description">
          Confirm the complete reviewed canonical plan for this source.
        </p>
        {plan && (
          <>
            <dl className="source-facts">
              <div>
                <dt>Source</dt>
                <dd>
                  {detail.name} <code>{selected}</code>
                </dd>
              </div>
              <div>
                <dt>Target</dt>
                <dd>
                  {detail.site_slug} / {detail.cluster_name}
                </dd>
              </div>
              <div>
                <dt>Plan received</dt>
                <dd>
                  <Timestamp value={plan.received} />
                </dd>
              </div>
            </dl>
            <PlanSummary plan={plan.value} />
          </>
        )}
        <p>
          Review rows are isolated, not automatically adopted or applied as
          normal updates. The backend revalidates the exact digest before
          issuing and consuming confirmation.
        </p>
        <ul>
          <li>Missing objects are retained. No deletes.</li>
          <li>Only this reviewed canonical plan is submitted.</li>
          <li>No automatic retry after an uncertain outcome.</li>
        </ul>
        {applying && (
          <div className="sync-pending">
            <p role="status">
              {phase === "validating"
                ? "Preparing / validating"
                : "Submitting / applying"}{" "}
              for {detail.name}.
            </p>
            <Elapsed start={started} />
            <p>
              Leaving a page does not cancel work already accepted by the
              backend.
            </p>
          </div>
        )}
        <div className="page-actions">
          <button ref={cancelButton} disabled={applying} onClick={closeDialog}>
            Cancel
          </button>
          <button className="primary" disabled={applying} onClick={submit}>
            Sync to NetBox
          </button>
        </div>
      </dialog>
    </section>
  );
}
