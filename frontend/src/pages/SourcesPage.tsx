import { useEffect, useState } from 'react';
import { fetchSource, fetchSources } from '../api/sources';
import type { Source } from '../api/sources';
import { runDiscovery } from '../api/discovery';
import type { DiscoveryResult } from '../api/discovery';
import { applySync, buildSyncPlan, ManualSyncRequestError, prepareSync, resultForSource } from '../api/sync';
import type { ManualSyncResult, SyncPlan } from '../api/sync';
import { fetchSchedule, updateSchedule } from '../api/schedule';
import type { Schedule } from '../api/schedule';

const genericSyncFailure = 'Manual sync request failed. No automatic retry was performed.';

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
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState('');
  const [classFilter, setClassFilter] = useState('ALL');
  const [kindFilter, setKindFilter] = useState('ALL');
  const [syncPlan, setSyncPlan] = useState<SyncPlan | null>(null);
  const [syncResult, setSyncResult] = useState<ManualSyncResult | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [editingSchedule, setEditingSchedule] = useState(false);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleInterval, setScheduleInterval] = useState(600);
  const [scheduleMessage, setScheduleMessage] = useState('');
  const visibleSyncResult = resultForSource(syncResult, selected);

  const buildPlan = async () => {
    if (!selected) return;
    setSyncing(true); setSyncResult(null); setSyncPlan(null);
    try { setSyncPlan(await buildSyncPlan(selected, new AbortController().signal)); }
    catch (failure) { setSyncResult({ sourceInstance: selected, kind: 'error', message: failure instanceof ManualSyncRequestError ? failure.message : genericSyncFailure }); }
    finally { setSyncing(false); }
  };

  const syncNow = async () => {
    if (!selected || !syncPlan || !window.confirm(`Apply the exact reviewed plan for ${selected}?`)) return;
    setSyncing(true); setSyncResult(null);
    try {
      const controller = new AbortController();
      const token = await prepareSync(selected, syncPlan.digest, controller.signal);
      setSyncResult({ sourceInstance: selected, kind: 'success', message: await applySync(selected, token, controller.signal) });
      setSyncPlan(null);
    } catch (failure) { setSyncResult({ sourceInstance: selected, kind: 'error', message: failure instanceof ManualSyncRequestError ? failure.message : genericSyncFailure }); }
    finally { setSyncing(false); }
  };

  const discover = async () => {
    if (!selected) return;
    const controller = new AbortController();
    setDiscovering(true); setDiscoveryError(''); setDiscovery(null);
    try { setDiscovery(await runDiscovery(selected, controller.signal)); }
    catch (failure) { setDiscoveryError(failure instanceof Error ? failure.message : 'Discovery failed.'); }
    finally { setDiscovering(false); }
  };

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    setLoading(true); setError(''); setDetail(null); setSchedule(null); setScheduleMessage(''); setEditingSchedule(false);
    const operation = selected
      ? fetchSource(selected, controller.signal).then((value) => {
        if (active) setDetail(value);
        return fetchSchedule(selected, controller.signal).catch((failure) => {
          if (active) setScheduleMessage(failure instanceof Error ? failure.message : 'Scheduling request failed.');
          return null;
        });
      }).then((scheduling) => { if (active && scheduling) { setSchedule(scheduling); setScheduleEnabled(scheduling.sync_enabled); setScheduleInterval(scheduling.sync_interval_seconds); } })
      : fetchSources(controller.signal).then((value) => { if (active) setSources(value); });
    operation.catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : 'Source data unavailable.');
    }).finally(() => { window.clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [selected, revision]);

  return <main>
    <div className="page-heading"><div><p className="eyebrow">READ-ONLY REGISTRY</p>
      <h1>{selected ? 'Source details' : 'Sources'}</h1>
      <p className="intro">Credentials and source identity are protected. Scheduling can be edited below.
        Connectivity and authentication are not checked here.</p></div>
      <button disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh</button>
    </div>
    {selected && <button onClick={() => { setSelected(null); setDiscovery(null); setSyncPlan(null); setSyncResult(null); setSchedule(null); }}>Back to sources</button>}
    {loading && <p role="status">Loading source configuration…</p>}
    {!loading && error && <p role="alert" className="source-error">{error}</p>}
    {!loading && !error && !selected && (sources.length === 0
      ? <p>No registered sources.</p>
      : <div className="source-table"><table><thead><tr>
        <th>Source instance</th><th>Type</th><th>Address</th><th>Site</th><th>Cluster</th>
        <th>Enabled</th><th>Automatic sync</th><th>Interval</th><th>Status</th>
      </tr></thead><tbody>{sources.map((source) => <tr key={source.source_instance}>
        <td><button onClick={() => { setSyncResult(null); setSelected(source.source_instance); }}>{source.source_instance}</button></td>
        <td>{source.type}</td><td>{source.address}</td><td>{source.site_slug}</td><td>{source.cluster_name}</td>
        <td>{source.enabled ? 'Yes' : 'No'}</td><td>{source.sync_enabled ? 'Configured on' : 'Configured off'}</td>
        <td>{source.sync_interval_seconds}s</td><td>{source.status.replaceAll('_', ' ')}</td>
      </tr>)}</tbody></table></div>)}
    {!loading && !error && detail && <><dl className="source-detail">
      {(Object.keys(detailLabels) as (keyof Source)[]).map((key) => <div key={key}>
        <dt>{detailLabels[key]}</dt><dd>{typeof detail[key] === 'boolean'
          ? (detail[key] ? 'Yes' : 'No') : String(detail[key])}</dd>
      </div>)}
    </dl>{!schedule && scheduleMessage && <p role="alert" className="source-error">{scheduleMessage}</p>}{schedule && <section className="discovery-review"><h2>Automatic synchronization</h2>
      <p>Status: {schedule.sync_enabled ? 'Enabled' : 'Disabled'}</p><p>Interval: Every {schedule.sync_interval_seconds} seconds</p>
      <p>Scheduler state: {schedule.scheduler_state}</p><p>Last scheduled run: {schedule.last_scheduled_run_at ? new Date(schedule.last_scheduled_run_at).toLocaleString() : 'None'}</p>
      <p>Next expected run: {schedule.next_expected_at ? new Date(schedule.next_expected_at).toLocaleString() : 'Not scheduled'}</p>
      {!editingSchedule ? <button onClick={() => { setEditingSchedule(true); setScheduleMessage(''); }}>Edit schedule</button> : <div>
        <label><input type="checkbox" checked={scheduleEnabled} onChange={(event) => setScheduleEnabled(event.target.checked)} /> Automatic sync</label>
        <label>Interval <select value={scheduleInterval} onChange={(event) => setScheduleInterval(Number(event.target.value))}>
          {[300, 600, 900, 1800, 3600, 21600, 86400].map((value) => <option key={value} value={value}>{value} seconds</option>)}
        </select></label>
        <label>Custom seconds <input type="number" min="60" max="86400" value={scheduleInterval} onChange={(event) => setScheduleInterval(Number(event.target.value))} /></label>
        <button onClick={async () => { setScheduleMessage(''); try { const updated = await updateSchedule(detail.source_instance, { sync_enabled: scheduleEnabled, sync_interval_seconds: scheduleInterval, expected_sync_enabled: schedule.sync_enabled, expected_sync_interval_seconds: schedule.sync_interval_seconds }, new AbortController().signal); setSchedule(updated); setEditingSchedule(false); setScheduleMessage(updated.sync_enabled ? 'Automatic synchronization updated.' : 'Automatic synchronization disabled. Manual synchronization remains available.'); } catch (failure) { setScheduleMessage(failure instanceof Error ? failure.message : 'Scheduling update failed.'); } }}>Save</button>
        <button onClick={() => { setEditingSchedule(false); setScheduleEnabled(schedule.sync_enabled); setScheduleInterval(schedule.sync_interval_seconds); }}>Cancel</button>
      </div>}{scheduleMessage && <p role="status">{scheduleMessage}</p>}
    </section>}<section className="discovery-review"><h2>Discovery / Preflight</h2>
      <p>Read-only: this contacts the source and NetBox but makes no NetBox changes.</p>
      <button disabled={discovering || !detail.enabled} onClick={discover}>Run discovery</button>
      {discovering && <p role="status">Running read-only discovery…</p>}
      {discoveryError && <p role="alert" className="source-error">{discoveryError}</p>}
      {discovery && <><div className="summary-grid">{Array.from(new Set(discovery.items.map((item) => item.classification))).map((classification) => <div key={classification}><strong>{classification.replaceAll('_', ' ')}</strong> <span>{discovery.items.filter((item) => item.classification === classification).length}</span></div>)}</div>
        <div className="filters"><label>Classification <select value={classFilter} onChange={(event) => setClassFilter(event.target.value)}><option>ALL</option>{Array.from(new Set(discovery.items.map((item) => item.classification))).map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Object kind <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}><option>ALL</option>{Array.from(new Set(discovery.items.map((item) => item.object_kind))).map((value) => <option key={value}>{value}</option>)}</select></label></div>
        <div className="source-table"><table><thead><tr><th>Kind</th><th>Name</th><th>Classification</th><th>Reason</th><th>Future action</th><th>NetBox match</th></tr></thead><tbody>{discovery.items.filter((item) => (classFilter === 'ALL' || item.classification === classFilter) && (kindFilter === 'ALL' || item.object_kind === kindFilter)).map((item) => <tr key={`${item.object_kind}:${item.external_id}`}><td>{item.object_kind}</td><td>{item.name}</td><td>{item.classification.replaceAll('_', ' ')}</td><td>{item.reason} ({item.reason_code})</td><td>{item.future_action}</td><td>{item.matched_object_name || '—'}</td></tr>)}</tbody></table></div></>}
    </section><section className="discovery-review"><h2>Plan / Sync Now</h2>
      <p>Build a read-only exact plan, review it, then explicitly confirm one source.</p>
      <button disabled={syncing || !detail.enabled} onClick={buildPlan}>Build plan</button>
      {syncing && <p role="status">Checking the current plan…</p>}
      {syncPlan && <><p>Plan digest: <code>{syncPlan.digest}</code></p>
        <div className="summary-grid">{actions(syncPlan).map(([action, count]) => <div key={action}><strong>{action.replaceAll('_', ' ')}</strong> <span>{count}</span></div>)}</div>
        <div className="source-table"><table><thead><tr><th>Kind</th><th>Name</th><th>Action</th><th>Reason</th></tr></thead><tbody>{syncPlan.items.map((item) => <tr key={`${item.object_kind}:${item.external_id}`}><td>{item.object_kind}</td><td>{item.name}</td><td>{item.action}</td><td>{item.reason}</td></tr>)}</tbody></table></div>
        <button disabled={!syncPlan.apply_allowed || syncing} onClick={syncNow}>Sync Now</button></>}
      {visibleSyncResult && <p role={visibleSyncResult.kind === 'error' ? 'alert' : 'status'}
        className={visibleSyncResult.kind === 'error' ? 'source-error' : undefined}>{visibleSyncResult.message}</p>}
    </section></>}
    <p className="intro">Systemd provides a fixed tick; Infra Sync derives each source schedule from persisted scheduled runs.</p>
  </main>;
}

function actions(plan: SyncPlan): [string, number][] {
  return Array.from(new Set(plan.items.map((item) => item.action))).map((action) => [action, plan.items.filter((item) => item.action === action).length]);
}
