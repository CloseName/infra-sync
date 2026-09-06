export type SyncAction = 'CREATE' | 'UPDATE' | 'NO_CHANGE' | 'REVIEW_REQUIRED' | 'BLOCKED' | 'IGNORED' | 'UNSUPPORTED' | 'RETAIN_ONLY';
export interface SyncPlanItem { object_kind: string; external_id: string; name: string; action: SyncAction; reason_code: string; reason: string; matched_object_id: string | number | null; before: unknown[][]; after: unknown[][]; }
export interface SyncPlan { source_instance: string; source_type: 'proxmox' | 'esxi'; source_fingerprint: string; target_fingerprint: string; provider_fingerprint: string; netbox_fingerprint: string; schema_version: number; planner_version: string; items: SyncPlanItem[]; apply_allowed: boolean; digest: string; }
export interface ManualSyncResult { sourceInstance: string; kind: 'success' | 'error'; message: string; }

export function resultForSource(result: ManualSyncResult | null, sourceInstance: string | null): ManualSyncResult | null {
  return result?.sourceInstance === sourceInstance ? result : null;
}

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const actions = ['CREATE', 'UPDATE', 'NO_CHANGE', 'REVIEW_REQUIRED', 'BLOCKED', 'IGNORED', 'UNSUPPORTED', 'RETAIN_ONLY'];
const genericFailure = 'Manual sync request failed. No automatic retry was performed.';
const errorMessages = {
  APPLY_LOCKED: 'Manual sync could not start: another sync is already running. No changes were made.',
  PLAN_STALE: 'The sync plan is no longer current. Build a new plan before syncing.',
  CONFIRMATION_EXPIRED: 'Sync confirmation expired. Build or confirm the plan again.',
  CONFIRMATION_INVALID: 'Sync confirmation is no longer valid. Confirm the plan again.',
  CONFIRMATION_SOURCE_MISMATCH: 'Sync confirmation does not match this source. Build a new plan.',
  PLAN_BLOCKED: 'This plan contains blocking conditions and cannot be applied.',
  FAILED_BEFORE_WRITE: 'Manual sync failed before any changes were written.',
  OUTCOME_UNCERTAIN: 'Manual sync stopped after the write phase began. The final NetBox state may be uncertain; review the source before retrying.',
} as const;
type ManualSyncErrorCode = keyof typeof errorMessages;

export class ManualSyncRequestError extends Error {
  constructor(message = genericFailure) { super(message); this.name = 'ManualSyncRequestError'; }
}

async function errorFor(response: Response): Promise<ManualSyncRequestError> {
  try {
    const value: unknown = await response.json();
    const code = record(value) && record(value.error) && typeof value.error.code === 'string'
      ? value.error.code : '';
    return new ManualSyncRequestError(
      Object.prototype.hasOwnProperty.call(errorMessages, code)
        ? errorMessages[code as ManualSyncErrorCode] : genericFailure,
    );
  } catch { return new ManualSyncRequestError(); }
}
const validPlan = (value: unknown, instance: string): value is SyncPlan => record(value)
  && value.source_instance === instance && (value.source_type === 'proxmox' || value.source_type === 'esxi')
  && typeof value.digest === 'string' && /^[a-f0-9]{64}$/.test(value.digest)
  && ['source_fingerprint', 'target_fingerprint', 'provider_fingerprint', 'netbox_fingerprint', 'planner_version'].every((key) => typeof value[key] === 'string')
  && typeof value.schema_version === 'number' && typeof value.apply_allowed === 'boolean'
  && Array.isArray(value.items) && value.items.every((item) => record(item) && typeof item.action === 'string' && actions.includes(item.action) && typeof item.name === 'string' && typeof item.object_kind === 'string' && typeof item.external_id === 'string' && typeof item.reason === 'string' && typeof item.reason_code === 'string' && Array.isArray(item.before) && Array.isArray(item.after));

const protectedPost = async (path: string, body: object, signal: AbortSignal) => {
  try { return await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-NetBox-Sync-CSRF': 'same-origin' }, credentials: 'same-origin', cache: 'no-store', signal, body: JSON.stringify(body) }); }
  catch { throw new ManualSyncRequestError(); }
};

export async function buildSyncPlan(instance: string, signal: AbortSignal): Promise<SyncPlan> {
  const response = await protectedPost(`/api/v1/sources/${encodeURIComponent(instance)}/sync-plan`, {}, signal);
  if (!response.ok) throw await errorFor(response);
  let value: unknown;
  try { value = await response.json(); } catch { throw new ManualSyncRequestError(); }
  if (!validPlan(value, instance)) throw new ManualSyncRequestError('Sync plan returned malformed data.');
  return value;
}

export async function prepareSync(instance: string, digest: string, signal: AbortSignal): Promise<string> {
  const response = await protectedPost(`/api/v1/sources/${encodeURIComponent(instance)}/sync-confirmations`, { plan_digest: digest, confirmed: true }, signal);
  if (!response.ok) throw await errorFor(response);
  let value: unknown;
  try { value = await response.json(); } catch { throw new ManualSyncRequestError(); }
  if (!record(value) || typeof value.confirmation_token !== 'string' || !/^[a-f0-9]{64}$/.test(value.confirmation_token)) throw new ManualSyncRequestError();
  return value.confirmation_token;
}

export async function applySync(instance: string, token: string, signal: AbortSignal): Promise<string> {
  const response = await protectedPost(`/api/v1/sources/${encodeURIComponent(instance)}/sync`, { confirmation_token: token }, signal);
  if (!response.ok) throw await errorFor(response);
  let value: unknown;
  try { value = await response.json(); } catch { throw new ManualSyncRequestError(); }
  if (!record(value) || value.status !== 'SUCCEEDED' || typeof value.plan_digest !== 'string' || !/^[a-f0-9]{64}$/.test(value.plan_digest)) throw new ManualSyncRequestError();
  return 'SUCCEEDED: Manual sync completed successfully.';
}
