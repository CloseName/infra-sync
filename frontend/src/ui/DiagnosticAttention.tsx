import { Link } from "react-router-dom";
import type { Diagnostics } from "../api/diagnostics";
import { diagnosticsUsable } from "./operations";
import { componentLabels, coverage } from "./diagnosticEvidence";
import { staleExplanation } from "./runEvidence";
import { runStatus } from "./status";
import { Timestamp } from "./primitives";
import { sourcePath, runPath } from "./routes";
import { interval } from "./format";
export function DiagnosticAttention({
  data,
  source,
}: {
  data: Diagnostics;
  source?: string;
}) {
  const warnings = data.warnings.filter(
    (w) => !source || w.source_instance === source,
  );
  const sources = diagnosticsUsable(data)
    ? data.sources.filter(
        (s) =>
          (!source || s.source_instance === source) &&
          ((s.latest_run &&
            !["SUCCEEDED", "RUNNING"].includes(s.latest_run.status)) ||
            (["UNHEALTHY", "UNAVAILABLE", "DEGRADED"].includes(s.status) &&
              !s.warnings.length &&
              !warnings.some((w) => w.source_instance === s.source_instance))),
      )
    : [];
  const components = source
    ? []
    : Object.entries(data.components).filter(([, c]) =>
        ["DEGRADED", "UNAVAILABLE"].includes(c.status),
      );
  const any = warnings.length + sources.length + components.length > 0;
  return (
    <div className="diagnostic-attention">
      <p className="muted">{coverage(data)}</p>
      {!any ? (
        <p>
          {diagnosticsUsable(data)
            ? "No attention items reported in this snapshot."
            : "No source assessment available. Review component evidence."}
        </p>
      ) : (
        <ul className="attention-rows">
          {components.map(([key, c]) => (
            <li key={key}>
              <div>
                <strong>
                  {componentLabels[key as keyof typeof componentLabels]} needs
                  attention
                </strong>
                <p>
                  {c.safe_message ||
                    "This check could not confirm availability."}
                </p>
              </div>
              <Timestamp value={c.checked_at} />
              <a href={"#component-" + key}>View check</a>
            </li>
          ))}
          {warnings.map((w, i) => (
            <li key={w.warning_code + (w.run_id ?? w.source_instance ?? i)}>
              <div>
                <strong>
                  {w.warning_code === "STALE_RUNNING"
                    ? "Completion unconfirmed"
                    : "Scheduled activity later than expected"}
                </strong>
                <p>
                  {w.source_instance ?? "Source not supplied"}
                  {w.trigger ? " · " + w.trigger : ""}
                </p>
                {w.warning_code === "STALE_RUNNING" && (
                  <p>{staleExplanation}</p>
                )}
                <details>
                  <summary>Evidence</summary>
                  <p>{w.safe_message}</p>
                  <p>Safe code: {w.warning_code}</p>
                  {w.run_id && <p>Run ID: {w.run_id}</p>}
                </details>
              </div>
              <div>
                {w.age_seconds !== null ? (
                  <>
                    {interval(w.age_seconds)} at snapshot
                    <small>
                      Started <Timestamp value={w.started_at} />
                    </small>
                  </>
                ) : (
                  <Timestamp
                    value={
                      w.started_at ??
                      data.sources.find(
                        (s) => s.source_instance === w.source_instance,
                      )?.next_expected_at
                    }
                  />
                )}
              </div>
              <div className="evidence-links">
                {w.run_id && <Link to={runPath(w.run_id)}>Open run</Link>}
                {w.source_instance && (
                  <Link
                    to={
                      sourcePath(w.source_instance) +
                      (w.warning_code === "SCHEDULED_ACTIVITY_DELAYED"
                        ? "/schedule"
                        : "/diagnostics")
                    }
                  >
                    {w.warning_code === "SCHEDULED_ACTIVITY_DELAYED"
                      ? "Open schedule"
                      : "Source diagnostics"}
                  </Link>
                )}
              </div>
            </li>
          ))}
          {sources.map((s) => (
            <li key={"source-" + s.source_instance}>
              <div>
                <strong>
                  {s.latest_run &&
                  !["SUCCEEDED", "RUNNING"].includes(s.latest_run.status)
                    ? runStatus(s.latest_run.status).label
                    : "Source needs attention"}
                </strong>
                <p>{s.source_instance}</p>
              </div>
              <Timestamp value={s.latest_run?.started_at} />
              <div className="evidence-links">
                {s.latest_run && (
                  <Link to={runPath(s.latest_run.run_id)}>Open run</Link>
                )}
                <Link to={sourcePath(s.source_instance) + "/diagnostics"}>
                  Source diagnostics
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
