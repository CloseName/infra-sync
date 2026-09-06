import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { runPath } from '../ui/routes';
import { fetchRuns, fetchRun } from '../api/runs';
import type { SyncRun } from '../api/runs';

const actionLabels: Record<keyof SyncRun['actions'], string> = {
  create: 'Create', update: 'Update', no_change: 'No change',
  review_required: 'Review required', blocked: 'Blocked', ignored: 'Ignored',
  unsupported: 'Unsupported', retain_only: 'Retain only',
};

const duration = (value: number | null) => value === null ? 'In progress' : `${value} ms`;
const changes = (run: SyncRun) => `${run.actions.create + run.actions.update} changes`;

export function RunsPage() {
  const { runId } = useParams();
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [selected, setSelected] = useState<SyncRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true); setError(false); setSelected(null);
    const request = runId ? fetchRun(runId, controller.signal).then(value => { if (active) setSelected(value); }) : fetchRuns(controller.signal).then(value => { if (active) setRuns(value); });
    request
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [revision, runId]);

  return <main><div className="page-heading"><div><p className="eyebrow">SYNC ACTIVITY</p>
    <h1>{runId ? 'Run details' : 'Run history'}</h1><p className="intro">Durable manual and scheduled synchronization outcomes.</p></div>
    <button disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh</button></div>
    {loading && <p role="status">Loading history...</p>}
    {!loading && error && <p role="alert" className="source-error">History could not be loaded.</p>}
    {!loading && !error && !runId && runs.length === 0 && <p>No synchronization runs recorded yet.</p>}
    {!loading && !error && runs.length > 0 && <div className="source-table"><table><thead><tr>
      <th scope="col">Time</th><th scope="col">Source</th><th scope="col">Type</th><th scope="col">Trigger</th><th scope="col">Status</th><th scope="col">Duration</th><th scope="col">Changes</th>
    </tr></thead><tbody>{runs.map((run) => <tr key={run.run_id}>
      <td><Link to={runPath(run.run_id)}>{new Date(run.started_at).toLocaleString()}</Link></td>
      <td>{run.source_instance}</td><td>{run.source_type}</td><td>{run.trigger}</td>
      <td><span className={`run-status run-status-${run.status.toLowerCase()}`}>{run.status.replaceAll('_', ' ')}</span></td>
      <td>{duration(run.duration_ms)}</td><td>{changes(run)}</td></tr>)}</tbody></table></div>}
    {selected && <section className="run-detail"><div className="component-heading"><h2>Run details</h2>
      <Link to="/runs">Back to runs</Link></div>
      <dl className="source-detail">
        <div><dt>Run ID</dt><dd>{selected.run_id}</dd></div>
        <div><dt>Source</dt><dd>{selected.source_instance}</dd></div>
        <div><dt>Source type</dt><dd>{selected.source_type}</dd></div>
        <div><dt>Trigger</dt><dd>{selected.trigger}</dd></div>
        <div><dt>Started</dt><dd>{new Date(selected.started_at).toLocaleString()}</dd></div>
        <div><dt>Finished</dt><dd>{selected.finished_at ? new Date(selected.finished_at).toLocaleString() : 'Still running'}</dd></div>
        <div><dt>Duration</dt><dd>{duration(selected.duration_ms)}</dd></div>
        <div><dt>Status</dt><dd>{selected.status}</dd></div>
        <div><dt>Created by</dt><dd>{selected.created_by}</dd></div>
        <div><dt>Plan digest</dt><dd>{selected.plan_digest ?? 'None'}</dd></div>
        <div><dt>Planner version</dt><dd>{selected.planner_version ?? 'None'}</dd></div>
      </dl><h3>Actions</h3><dl className="source-detail">{(Object.keys(actionLabels) as (keyof SyncRun['actions'])[]).map((name) =>
        <div key={name}><dt>{actionLabels[name]}</dt><dd>{selected.actions[name]}</dd></div>)}</dl>
      {selected.error_code && <div className="source-error"><h3>Error</h3>
        <p><code>{selected.error_code}</code></p><p>{selected.error_message_safe ?? 'Synchronization failed.'}</p></div>}
    </section>}
  </main>;
}
