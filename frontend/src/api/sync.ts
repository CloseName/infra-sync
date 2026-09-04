export type SyncAction = 'CREATE' | 'UPDATE' | 'NO_CHANGE' | 'REVIEW_REQUIRED' | 'BLOCKED' | 'IGNORED' | 'UNSUPPORTED' | 'RETAIN_ONLY';
export interface SyncPlanItem { object_kind: string; external_id: string; name: string; action: SyncAction; reason_code: string; reason: string; matched_object_id: string | number | null; before: unknown[][]; after: unknown[][]; }
export interface SyncPlan { source_instance: string; source_type: 'proxmox' | 'esxi'; source_fingerprint: string; target_fingerprint: string; provider_fingerprint: string; netbox_fingerprint: string; schema_version: number; planner_version: string; items: SyncPlanItem[]; apply_allowed: boolean; digest: string; }

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const actions = ['CREATE', 'UPDATE', 'NO_CHANGE', 'REVIEW_REQUIRED', 'BLOCKED', 'IGNORED', 'UNSUPPORTED', 'RETAIN_ONLY'];
const validPlan = (value: unknown, instance: string): value is SyncPlan => record(value)
  && value.source_instance === instance && (value.source_type === 'proxmox' || value.source_type === 'esxi')
  && typeof value.digest === 'string' && /^[a-f0-9]{64}$/.test(value.digest)
  && ['source_fingerprint', 'target_fingerprint', 'provider_fingerprint', 'netbox_fingerprint', 'planner_version'].every((key) => typeof value[key] === 'string')
  && typeof value.schema_version === 'number' && typeof value.apply_allowed === 'boolean'
  && Array.isArray(value.items) && value.items.every((item) => record(item) && typeof item.action === 'string' && actions.includes(item.action) && typeof item.name === 'string' && typeof item.object_kind === 'string' && typeof item.external_id === 'string' && typeof item.reason === 'string' && typeof item.reason_code === 'string' && Array.isArray(item.before) && Array.isArray(item.after));

const protectedPost = async (path: string, body: object, signal: AbortSignal) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Infra-Sync-CSRF': 'same-origin' }, credentials: 'same-origin', cache: 'no-store', signal, body: JSON.stringify(body) });

export async function buildSyncPlan(instance: string, signal: AbortSignal): Promise<SyncPlan> {
  const response = await protectedPost(`/api/v1/sources/${encodeURIComponent(instance)}/sync-plan`, {}, signal);
  if (!response.ok) throw new Error('Sync plan could not be built. No changes were made.');
  const value: unknown = await response.json();
  if (!validPlan(value, instance)) throw new Error('Sync plan returned malformed data.');
  return value;
}

export async function prepareSync(instance: string, digest: string, signal: AbortSignal): Promise<string> {
  const response = await protectedPost(`/api/v1/sources/${encodeURIComponent(instance)}/sync-confirmations`, { plan_digest: digest, confirmed: true }, signal);
  const value: unknown = await response.json();
  if (!response.ok || !record(value) || typeof value.confirmation_token !== 'string' || !/^[a-f0-9]{64}$/.test(value.confirmation_token)) throw new Error('Plan changed or confirmation failed. Build the plan again.');
  return value.confirmation_token;
}

export async function applySync(instance: string, token: string, signal: AbortSignal): Promise<string> {
  const response = await protectedPost(`/api/v1/sources/${encodeURIComponent(instance)}/sync`, { confirmation_token: token }, signal);
  const value: unknown = await response.json();
  if (!response.ok || !record(value) || value.status !== 'SUCCEEDED' || typeof value.plan_digest !== 'string' || !/^[a-f0-9]{64}$/.test(value.plan_digest)) throw new Error('Sync did not complete. Build a new plan before retrying.');
  return value.status;
}
