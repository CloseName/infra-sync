import { Link } from "react-router-dom";
import { fetchDiagnostics } from "../api/diagnostics";
import { useResource } from "../ui/useResource";
import { ResourceFeedback } from "../ui/ResourceFeedback";
import { Badge, PageHeader, Timestamp } from "../ui/primitives";
import { healthStatus, runStatus, scheduleStates } from "../ui/status";
import {
  componentLabels,
  componentReason,
  aggregateReason,
} from "../ui/diagnosticEvidence";
import type { ComponentKey } from "../ui/diagnosticEvidence";
import { diagnosticsUsable } from "../ui/operations";
import { DiagnosticAttention } from "../ui/DiagnosticAttention";
import { staleEvidence } from "../ui/runEvidence";
import { sourcePath, runPath } from "../ui/routes";
export function DiagnosticsPage() {
  const resource = useResource(fetchDiagnostics),
    data = resource.data;
  return (
    <main className="operations-workspace">
      <PageHeader
        title="Diagnostics"
        description="Checks and recorded activity, with evidence for investigation."
        actions={
          <button disabled={resource.loading} onClick={resource.refresh}>
            Refresh
          </button>
        }
      />
      <ResourceFeedback
        resource={resource}
        label="diagnostics"
        evidenceAt={data?.generated_at}
      />
      {data && (
        <>
          <section
            className="diagnostic-summary source-panel"
            aria-label="System assessment"
          >
            <div>
              <h2>
                <Badge
                  value={healthStatus(data.overall_status)}
                  code={data.overall_status}
                />
              </h2>
              <p>{aggregateReason(data)}</p>
            </div>
            <p>
              Snapshot <Timestamp value={data.generated_at} />
            </p>
          </section>
          <section className="source-panel">
            <h2>Component checks</h2>
            <div className="diagnostic-components">
              {(Object.keys(componentLabels) as ComponentKey[]).map((key) => {
                const c = data.components[key];
                return (
                  <article
                    id={"component-" + key}
                    key={key}
                    className="diagnostic-component"
                  >
                    <div>
                      <h3>{componentLabels[key]}</h3>
                      <Badge value={healthStatus(c.status)} code={c.status} />
                    </div>
                    <div>
                      <p>{componentReason(key, c)}</p>
                      <small>
                        {key === "scheduler"
                          ? "Last recorded activity"
                          : "Last response"}
                        : <Timestamp value={c.last_seen_at} />
                      </small>
                      <details>
                        <summary>Technical evidence</summary>
                        <dl className="technical-facts">
                          <div>
                            <dt>Recorded status</dt>
                            <dd>{c.status}</dd>
                          </div>
                          <div>
                            <dt>Checked at</dt>
                            <dd>
                              <Timestamp value={c.checked_at} />
                            </dd>
                          </div>
                          <div>
                            <dt>Last success</dt>
                            <dd>
                              <Timestamp value={c.last_success_at} />
                            </dd>
                          </div>
                          <div>
                            <dt>Next expected</dt>
                            <dd>
                              <Timestamp value={c.next_expected_at} />
                            </dd>
                          </div>
                          <div>
                            <dt>Safe code</dt>
                            <dd>{c.safe_code ?? "None reported"}</dd>
                          </div>
                          {c.safe_message && (
                            <div>
                              <dt>Safe message</dt>
                              <dd>{c.safe_message}</dd>
                            </div>
                          )}
                        </dl>
                      </details>
                    </div>
                    <div className="muted">
                      Checked <Timestamp value={c.checked_at} />
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
          <section className="source-panel">
            <h2>Attention</h2>
            <DiagnosticAttention data={data} />
          </section>
          <section className="source-panel">
            <h2>Source evidence</h2>
            <p className="muted">
              Derived from configuration and persisted runs. This does not
              verify source connectivity or a live scheduler heartbeat.
            </p>
            {!diagnosticsUsable(data) ? (
              <p>
                Source evidence unavailable. Registry and run history checks
                must both succeed.
              </p>
            ) : data.sources.length === 0 ? (
              <p>
                No sources configured. <Link to="/sources">Open Sources</Link>
              </p>
            ) : (
              <div
                className="source-table"
                role="region"
                aria-label="Source diagnostic evidence"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      {[
                        "Source",
                        "Assessment",
                        "Latest run",
                        "Scheduled activity",
                        "Last success",
                      ].map((label) => (
                        <th key={label} scope="col">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((s) => (
                      <tr key={s.source_instance}>
                        <td>
                          <Link
                            to={sourcePath(s.source_instance) + "/diagnostics"}
                          >
                            {s.source_instance}
                          </Link>
                          <small>
                            {s.source_type === "proxmox"
                              ? "Proxmox VE"
                              : "VMware ESXi"}
                          </small>
                        </td>
                        <td>
                          <Badge value={healthStatus(s.status)} />
                        </td>
                        <td>
                          {s.latest_run ? (
                            <>
                              <Link to={runPath(s.latest_run.run_id)}>
                                <Badge
                                  value={runStatus(
                                    s.latest_run.status,
                                    !!staleEvidence(
                                      s.latest_run,
                                      s.source_instance,
                                      data,
                                    ),
                                  )}
                                />
                              </Link>
                              <small>
                                <Timestamp value={s.latest_run.started_at} />
                              </small>
                            </>
                          ) : (
                            "No runs recorded"
                          )}
                        </td>
                        <td>
                          <Link
                            to={sourcePath(s.source_instance) + "/schedule"}
                          >
                            <Badge value={scheduleStates[s.scheduler_state]} />
                          </Link>
                          <small>
                            Last scheduled:{" "}
                            <Timestamp value={s.last_scheduled_run_at} />
                          </small>
                        </td>
                        <td>
                          <Timestamp value={s.latest_success_at} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
