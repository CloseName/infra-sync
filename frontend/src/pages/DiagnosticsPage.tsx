import { useEffect, useState } from 'react';
import { fetchDiagnostics } from '../api/diagnostics';
import type { DiagnosticCode, Diagnostics, DiagnosticStatus } from '../api/diagnostics';

const components = {
  api: 'API', registry: 'Registry DB', run_history: 'Run History',
  discovery_worker: 'Discovery Worker', apply_worker: 'Apply Worker', scheduler: 'Scheduled Activity',
} as const;
const messages: Record<DiagnosticCode, string> = {
  REGISTRY_UNAVAILABLE: 'Source registry is unavailable.',
  RUN_HISTORY_UNAVAILABLE: 'Synchronization history is unavailable.',
  DISCOVERY_WORKER_UNAVAILABLE: 'Discovery worker is unavailable.',
  APPLY_WORKER_UNAVAILABLE: 'Apply worker is unavailable.',
  SCHEDULED_ACTIVITY_DELAYED: 'Scheduled synchronization activity is later than expected.',
  STALE_RUNNING: 'Synchronization run has remained RUNNING longer than expected. Automatic retry was not performed.',
};
const shownStatus = (status: DiagnosticStatus) => status.replaceAll('_', ' ');
const time = (value: string | null) => value ? new Date(value).toLocaleString() : 'None recorded';

export function DiagnosticsPage() {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoading(true); setError(false);
    fetchDiagnostics(controller.signal).then((value) => { if (active) setData(value); })
      .catch(() => { if (active) { setError(true); setData(null); } })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [revision]);
  return <main><div className="page-heading"><div><p className="eyebrow">OPERATOR DIAGNOSTICS</p>
    <h1>Diagnostics</h1><p className="intro">Read-only runtime, worker, history, and source visibility.</p></div>
    <button disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh</button></div>
    {loading && <p role="status">Loading diagnostics...</p>}
    {!loading && error && <p role="alert" className="source-error">Diagnostics unavailable.</p>}
    {!loading && data && <><section className="overview"><div><span className="eyebrow">SYSTEM STATUS</span>
      <h2>{data.overall_status}</h2><p>Generated {new Date(data.generated_at).toLocaleString()}</p></div>
      <span className={`diagnostic-status diagnostic-${data.overall_status.toLowerCase()}`}>{data.overall_status}</span></section>
      <section className="components" aria-label="Diagnostic components">{Object.entries(components).map(([key, label]) => {
        const component = data.components[key as keyof typeof components];
        return <article className="component" key={key}><div className="component-heading"><h3>{label}</h3>
          <span className={`diagnostic-status diagnostic-${component.status.toLowerCase()}`}>{shownStatus(component.status)}</span></div>
          <p>{component.safe_code ? messages[component.safe_code] : 'Available.'}</p>
          {component.last_seen_at && <p>Last activity: {time(component.last_seen_at)}</p>}</article>;
      })}</section>
      <h2>Sources</h2>{data.sources.length === 0 ? <p>No sources configured.</p> :
        <div className="source-table"><table><thead><tr><th>Source</th><th>Type</th><th>Status</th>
          <th>Schedule</th><th>Last Run</th><th>Last Success</th><th>Next Expected</th><th>Trigger</th><th>Warnings</th></tr></thead>
          <tbody>{data.sources.map((source) => <tr key={source.source_instance}><td>{source.source_instance}</td>
            <td>{source.source_type}</td><td>{source.status}</td><td>{source.scheduler_state}</td><td>{time(source.latest_run?.started_at ?? null)}</td>
            <td>{time(source.latest_success_at)}</td><td>{time(source.next_expected_at)}</td><td>{source.latest_run?.trigger ?? 'None'}</td>
            <td>{source.warning_count}</td></tr>)}</tbody></table></div>}
      {data.sources.length > 0 && data.sources.every((source) => source.latest_run === null)
        && <p>No synchronization runs recorded yet.</p>}
      <section className="diagnostic-warnings"><h2>Warnings</h2>{data.warnings.length === 0 ? <p>No warnings.</p>
        : data.warnings.map((warning, index) => <article className="source-error" key={`${warning.warning_code}-${warning.run_id ?? index}`}>
          <h3>{warning.warning_code.replaceAll('_', ' ')}</h3><p>{warning.warning_code in messages
            ? messages[warning.warning_code] : 'Diagnostic warning requires attention.'}</p>
          {warning.source_instance && <p>Source: {warning.source_instance}</p>}
          {warning.source_type && <p>Type: {warning.source_type}</p>}
          {warning.trigger && <p>Trigger: {warning.trigger}</p>}
          {warning.started_at && <p>Started: {time(warning.started_at)}</p>}</article>)}</section></>}
  </main>;
}
