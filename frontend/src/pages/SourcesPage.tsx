import { useEffect, useState } from 'react';
import { fetchSource, fetchSources } from '../api/sources';
import type { Source } from '../api/sources';

const detailLabels: Record<keyof Source, string> = {
  source_instance: 'Source instance', type: 'Type', name: 'Display name', address: 'Address',
  enabled: 'Enabled', sync_enabled: 'Automatic sync configured', verify_ssl: 'Verify TLS',
  sync_interval_seconds: 'Configured interval (seconds)', site_slug: 'Site slug', cluster_name: 'Cluster',
  platform_slug: 'Platform slug', device_role_slug: 'Device role slug', device_type_slug: 'Device type slug',
  cluster_type_slug: 'Cluster type slug', legacy_identity_owner: 'Legacy identity owner', status: 'Configuration status',
};

export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Source | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    setLoading(true); setError(''); setDetail(null);
    const operation = selected
      ? fetchSource(selected, controller.signal).then((value) => { if (active) setDetail(value); })
      : fetchSources(controller.signal).then((value) => { if (active) setSources(value); });
    operation.catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : 'Source data unavailable.');
    }).finally(() => { window.clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [selected, revision]);

  return <main>
    <div className="page-heading"><div><p className="eyebrow">READ-ONLY REGISTRY</p>
      <h1>{selected ? 'Source details' : 'Sources'}</h1>
      <p className="intro">Credentials are protected. Connectivity and authentication are not checked here.
        Editing is not available.</p></div>
      <button disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh</button>
    </div>
    {selected && <button onClick={() => setSelected(null)}>Back to sources</button>}
    {loading && <p role="status">Loading source configuration…</p>}
    {!loading && error && <p role="alert" className="source-error">{error}</p>}
    {!loading && !error && !selected && (sources.length === 0
      ? <p>No registered sources.</p>
      : <div className="source-table"><table><thead><tr>
        <th>Source instance</th><th>Type</th><th>Address</th><th>Site</th><th>Cluster</th>
        <th>Enabled</th><th>Automatic sync</th><th>Interval</th><th>Status</th>
      </tr></thead><tbody>{sources.map((source) => <tr key={source.source_instance}>
        <td><button onClick={() => setSelected(source.source_instance)}>{source.source_instance}</button></td>
        <td>{source.type}</td><td>{source.address}</td><td>{source.site_slug}</td><td>{source.cluster_name}</td>
        <td>{source.enabled ? 'Yes' : 'No'}</td><td>{source.sync_enabled ? 'Configured on' : 'Configured off'}</td>
        <td>{source.sync_interval_seconds}s</td><td>{source.status.replaceAll('_', ' ')}</td>
      </tr>)}</tbody></table></div>)}
    {!loading && !error && detail && <dl className="source-detail">
      {(Object.keys(detailLabels) as (keyof Source)[]).map((key) => <div key={key}>
        <dt>{detailLabels[key]}</dt><dd>{typeof detail[key] === 'boolean'
          ? (detail[key] ? 'Yes' : 'No') : String(detail[key])}</dd>
      </div>)}
    </dl>}
    <p className="intro">Flags and interval describe registry configuration, not scheduler execution or source health.
      The existing systemd scheduler is unchanged.</p>
  </main>;
}
