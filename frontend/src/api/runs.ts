export type RunStatus = 'RUNNING' | 'SUCCEEDED' | 'FAILED_BEFORE_WRITE' | 'PARTIALLY_APPLIED' | 'OUTCOME_UNCERTAIN' | 'BLOCKED' | 'LOCKED' | 'FAILED';
export interface RunActions { create: number; update: number; no_change: number; review_required: number; blocked: number; ignored: number; unsupported: number; retain_only: number; }
export interface SyncRun { run_id: string; source_instance: string; source_type: 'proxmox' | 'esxi'; trigger: 'manual' | 'scheduled'; status: RunStatus; started_at: string; finished_at: string | null; duration_ms: number | null; plan_digest: string | null; planner_version: string | null; actions: RunActions; error_code: string | null; error_message_safe: string | null; created_by: string; }

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const statuses = ['RUNNING', 'SUCCEEDED', 'FAILED_BEFORE_WRITE', 'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN', 'BLOCKED', 'LOCKED', 'FAILED'];
const actionNames = ['create', 'update', 'no_change', 'review_required', 'blocked', 'ignored', 'unsupported', 'retain_only'];
const nullableString = (value: unknown) => value === null || typeof value === 'string';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const timestamp = (value: unknown) => typeof value === 'string' && !Number.isNaN(Date.parse(value));
const digest = (value: unknown) => value === null || (typeof value === 'string' && /^[a-f0-9]{64}$/.test(value));
const validActions = (value: unknown) => record(value)
  && actionNames.every((name) => Number.isSafeInteger(value[name]) && Number(value[name]) >= 0);

export function isSyncRun(value: unknown): value is SyncRun {
  return record(value) && typeof value.run_id === 'string' && uuid.test(value.run_id)
    && typeof value.source_instance === 'string' && value.source_instance !== ''
    && (value.source_type === 'proxmox' || value.source_type === 'esxi')
    && (value.trigger === 'manual' || value.trigger === 'scheduled')
    && typeof value.status === 'string' && statuses.includes(value.status)
    && timestamp(value.started_at) && (value.finished_at === null || timestamp(value.finished_at))
    && (value.duration_ms === null || (Number.isSafeInteger(value.duration_ms) && Number(value.duration_ms) >= 0))
    && digest(value.plan_digest) && nullableString(value.planner_version)
    && nullableString(value.error_code) && nullableString(value.error_message_safe)
    && typeof value.created_by === 'string' && validActions(value.actions);
}

export async function fetchRuns(signal: AbortSignal): Promise<SyncRun[]> {
  let response: Response;
  try { response = await fetch('/api/v1/runs?limit=50', { signal, cache: 'no-store' }); }
  catch { throw new Error('History could not be loaded.'); }
  if (!response.ok) throw new Error('History could not be loaded.');
  let value: unknown;
  try { value = await response.json(); } catch { throw new Error('History could not be loaded.'); }
  if (!record(value) || !Array.isArray(value.runs) || !value.runs.every(isSyncRun)) throw new Error('History could not be loaded.');
  return value.runs;
}

export async function fetchRun(id: string, signal: AbortSignal): Promise<SyncRun> {
 const response = await fetch('/api/v1/runs/' + encodeURIComponent(id), { signal, cache: 'no-store' });
 if (!response.ok) throw new Error('Run could not be loaded.');
 const value: unknown = await response.json();
 if (!isSyncRun(value) || value.run_id !== id) throw new Error('Run returned malformed data.');
 return value;
}
