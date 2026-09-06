import { useEffect, useState } from 'react';
import { fetchHealth } from '../api/health';
import { StatusBadge } from '../components/StatusBadge';
import type { ComponentName, SystemHealth } from '../types/health';

const labels: Record<ComponentName, string> = {
  api: 'API', application: 'Application', database: 'PostgreSQL', registry: 'Source registry', netbox: 'NetBox',
};

export function SystemHealthPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setLoading(true);
    setError(false);
    fetchHealth(controller.signal)
      .then((result) => {
        if (active) { setHealth(result); setCheckedAt(new Date()); }
      })
      .catch(() => { if (active) { setError(true); setHealth(null); } })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [revision]);

  return <main>
    <div className="page-heading">
      <div><p className="eyebrow">SYSTEM OVERVIEW</p><h1>System health</h1>
        <p className="intro">A read-only view of the NetBox Sync application and its dependencies.</p></div>
      <button onClick={() => setRevision((value) => value + 1)} disabled={loading}>
        {loading ? 'Checking…' : 'Refresh health'}
      </button>
    </div>
    <section className="overview" aria-live="polite" aria-busy={loading}>
      <div><span className="eyebrow">OVERALL READINESS</span>
        <h2>{error ? 'Unable to reach health API' : loading ? 'Checking system health' : 'Application readiness'}</h2>
        <p>{error ? 'No current status is available. Check the API connection and try again.'
          : 'Readiness does not indicate the outcome of a synchronization run.'}</p></div>
      {!loading && !error && health && <StatusBadge status={health.status} />}
      {error && <span className="status status-unavailable" role="alert">API unavailable</span>}
    </section>
    {health && !error && <section className="components" aria-label="Component health">
      {(Object.keys(labels) as ComponentName[]).map((name) => {
        const component = health.components[name];
        return <article className="component" key={name}>
          <div className="component-heading"><h3>{labels[name]}</h3><StatusBadge status={component.status} /></div>
          <p>{component.message}</p>
          {component.error_code && <code>{component.error_code}</code>}
        </article>;
      })}
    </section>}
    <footer className="page-footer">
      <span>{checkedAt && !error ? `Last successful response: ${checkedAt.toLocaleTimeString()}` : 'No successful response yet'}</span>
      <span>Source authentication and discovery are not performed.</span>
    </footer>
  </main>;
}
