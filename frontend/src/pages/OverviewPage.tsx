import { Link } from "react-router-dom";
import { fetchSources } from "../api/sources";
import { fetchDiagnostics } from "../api/diagnostics";
import { fetchRuns } from "../api/runs";
import { useResource } from "../ui/useResource";
import { ResourceNotice } from "../ui/ResourceNotice";
import {
  Badge,
  EmptyState,
  LoadingState,
  PageHeader,
  Timestamp,
} from "../ui/primitives";
import { healthStatus, runStatus } from "../ui/status";
import { duration } from "../ui/format";
import {
  composeSources,
  diagnosticsUsable,
  overviewReason,
} from "../ui/operations";
import { sourcePath, runPath } from "../ui/routes";
export function OverviewPage() {
  const sources = useResource(fetchSources),
    diagnostics = useResource(fetchDiagnostics),
    runs = useResource(fetchRuns);
  const data = diagnostics.data;
  const usable = diagnosticsUsable(data);
  const rows = composeSources(sources.data ?? [], data);
  const attention = rows
    .filter((row) => row.attention)
    .sort(
      (a, b) =>
        a.attention!.priority - b.attention!.priority ||
        a.source.source_instance.localeCompare(b.source.source_instance),
    )
    .slice(0, 5);
  const expected = usable
    ? data!.sources
        .filter((s) => s.enabled && s.sync_enabled && s.next_expected_at)
        .sort((a, b) => a.next_expected_at!.localeCompare(b.next_expected_at!))
        .slice(0, 5)
    : [];
  const refresh = () => {
    sources.refresh();
    diagnostics.refresh();
    runs.refresh();
  };
  const staleIds = new Set(data?.stale_runs.map((w) => w.run_id));
  const running = runs.data?.filter(
    (run) => run.status === "RUNNING" && !staleIds.has(run.run_id),
  );
  return (
    <main>
      <PageHeader
        title="Overview"
        description="Synchronization activity and the evidence behind it."
        actions={
          <button
            disabled={sources.loading || diagnostics.loading || runs.loading}
            onClick={refresh}
          >
            Refresh
          </button>
        }
      />
      <ResourceNotice
        resource={diagnostics}
        name="Diagnostics"
        retry={diagnostics.refresh}
      />
      <section
        className="panel overview-summary"
        aria-label="Overall diagnostics"
      >
        {data ? (
          <>
            <Badge
              value={healthStatus(data.overall_status)}
              code={data.overall_status}
            />
            <p>{overviewReason(data)}</p>
            <small>
              Aggregate: {data.overall_status} · Checked{" "}
              <Timestamp value={data.generated_at} />
            </small>
            <Link to="/diagnostics">Open diagnostics →</Link>
          </>
        ) : diagnostics.loading ? (
          <LoadingState label="Loading diagnostic summary…" />
        ) : (
          <p>Overall diagnostics unavailable.</p>
        )}
      </section>
      <div className="summary-panels">
        <section className="panel">
          <h2>Sources</h2>
          <ResourceNotice
            resource={sources}
            name="Sources"
            retry={sources.refresh}
          />
          {sources.data ? (
            <>
              <Link className="metric" to="/sources">
                {sources.data.length} registered
              </Link>
              {diagnostics.loading && !data ? (
                <LoadingState label="Loading source diagnostic states…" />
              ) : (
                <div className="status-counts">
                  {[
                    "HEALTHY",
                    "DEGRADED",
                    "UNHEALTHY",
                    "UNKNOWN",
                    "UNAVAILABLE",
                  ].map((status) => {
                    const count = rows.filter(
                      (row) =>
                        (row.diagnostic?.status ?? "UNAVAILABLE") === status,
                    ).length;
                    return (
                      <Link key={status} to={`/sources?health=${status}`}>
                        {healthStatus(status).label}: {count}
                      </Link>
                    );
                  })}
                </div>
              )}
            </>
          ) : sources.loading ? (
            <LoadingState />
          ) : (
            <p>Source count unavailable.</p>
          )}
        </section>
        <section className="panel">
          <h2>Activity</h2>
          {runs.data ? (
            <>
              <p>
                <Link to="/runs">
                  {running?.length} RUNNING records in the latest{" "}
                  {runs.data.length} runs
                </Link>
              </p>
              <p className="muted">Recorded status; not a live worker check.</p>
            </>
          ) : runs.loading ? (
            <LoadingState />
          ) : (
            <p>Recent activity unavailable.</p>
          )}
          {data && data.components.run_history.status === "HEALTHY" ? (
            <p>
              <Link to="/diagnostics">
                {data.stale_runs.length} completion-unconfirmed records returned
              </Link>
              <small>
                Diagnostic selection is limited to 100; not a global total.
              </small>
            </p>
          ) : (
            <p>Stale record evidence unavailable.</p>
          )}
        </section>
      </div>
      <div className="overview-grid">
        <section className="panel">
          <h2>Needs attention</h2>
          {data &&
            Object.entries(data.components)
              .filter(([, c]) => ["UNAVAILABLE", "DEGRADED"].includes(c.status))
              .map(([key, c]) => (
                <p key={key}>
                  <Link to="/diagnostics">
                    {key.replaceAll("_", " ")}: {healthStatus(c.status).label}
                  </Link>
                </p>
              ))}
          {!sources.data || !usable ? (
            <p>Source attention cannot be fully evaluated.</p>
          ) : attention.length ? (
            <ul className="activity-list">
              {attention.map((row) => (
                <li key={row.source.source_instance}>
                  <Link to={sourcePath(row.source.source_instance)}>
                    {row.source.name}
                  </Link>
                  <span>{row.attention!.label}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No source attention items reported.</p>
          )}
          {data?.stale_runs.slice(0, 3).map((w) => (
            <p key={w.run_id ?? w.source_instance}>
              {w.run_id ? (
                <Link to={runPath(w.run_id)}>
                  Completion unconfirmed: {w.source_instance}
                </Link>
              ) : (
                "Completion unconfirmed"
              )}
            </p>
          ))}
          <Link to="/sources?attention=yes">
            View sources needing attention →
          </Link>
        </section>
        <section className="panel">
          <h2>Next expected</h2>
          {!usable ? (
            <p>Schedule evidence unavailable.</p>
          ) : expected.length ? (
            <ul className="activity-list">
              {expected.map((s) => (
                <li key={s.source_instance}>
                  <Link to={sourcePath(s.source_instance)}>
                    {sources.data?.find(
                      (source) => source.source_instance === s.source_instance,
                    )?.name ?? s.source_instance}
                  </Link>
                  <Timestamp value={s.next_expected_at} />
                </li>
              ))}
            </ul>
          ) : (
            <p>No next expected runs reported.</p>
          )}
          <p className="muted">
            Expected times are derived from configuration and history; start
            times are not guaranteed.
          </p>
        </section>
      </div>
      <section className="panel">
        <h2>Recent runs</h2>
        <ResourceNotice
          resource={runs}
          name="Run history"
          retry={runs.refresh}
        />
        {runs.data ? (
          runs.data.length ? (
            <div
              className="scroll-region"
              tabIndex={0}
              role="region"
              aria-label="Recent runs"
            >
              <table>
                <caption className="sr-only">
                  Latest eight recorded runs
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Started</th>
                    <th scope="col">Trigger</th>
                    <th scope="col">Outcome</th>
                    <th scope="col">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.slice(0, 8).map((run) => (
                    <tr key={run.run_id}>
                      <th scope="row">
                        <Link to={sourcePath(run.source_instance)}>
                          {sources.data?.find(
                            (s) => s.source_instance === run.source_instance,
                          )?.name ?? run.source_instance}
                        </Link>
                      </th>
                      <td>
                        <Link to={runPath(run.run_id)}>
                          <Timestamp value={run.started_at} />
                        </Link>
                      </td>
                      <td>{run.trigger}</td>
                      <td>
                        <Badge
                          value={runStatus(
                            run.status,
                            staleIds.has(run.run_id),
                          )}
                          code={run.status}
                        />
                      </td>
                      <td>{duration(run.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No runs have been recorded yet.">
              <Link to="/sources">Open Sources</Link>
            </EmptyState>
          )
        ) : runs.loading ? (
          <LoadingState table label="Loading recent runs…" />
        ) : (
          <p>No run data available.</p>
        )}
        <Link to="/runs">Open run history →</Link>
      </section>
    </main>
  );
}
