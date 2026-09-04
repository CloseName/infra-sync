export type Classification = 'MANAGED' | 'REVIEW_REQUIRED' | 'WOULD_CREATE' | 'IGNORED' | 'UNSUPPORTED' | 'CONFLICT' | 'NO_CHANGE';
export interface DiscoveryItem { object_kind: 'host' | 'qemu' | 'lxc' | 'vm'; name: string; external_id: string; classification: Classification; reason_code: string; reason: string; future_action: 'none' | 'create' | 'update' | 'review' | 'ignored' | 'unsupported'; matched_object_id: string | number | null; matched_object_name: string | null; }
export interface DiscoveryResult { source_instance: string; source_type: 'proxmox' | 'esxi'; site_slug: string; cluster_name: string; items: DiscoveryItem[]; }
const classifications = ['MANAGED', 'REVIEW_REQUIRED', 'WOULD_CREATE', 'IGNORED', 'UNSUPPORTED', 'CONFLICT', 'NO_CHANGE'];
const actions = ['none', 'create', 'update', 'review', 'ignored', 'unsupported'];
const kinds = ['host', 'qemu', 'lxc', 'vm'];
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const item = (value: unknown): value is DiscoveryItem => record(value)
  && typeof value.object_kind === 'string' && kinds.includes(value.object_kind)
  && ['name', 'external_id', 'reason_code', 'reason'].every((key) => typeof value[key] === 'string')
  && typeof value.classification === 'string' && classifications.includes(value.classification)
  && typeof value.future_action === 'string' && actions.includes(value.future_action)
  && (value.matched_object_id === null || typeof value.matched_object_id === 'string' || typeof value.matched_object_id === 'number')
  && (value.matched_object_name === null || typeof value.matched_object_name === 'string');

export async function runDiscovery(instance: string, signal: AbortSignal): Promise<DiscoveryResult> {
  let response: Response;
  try { response = await fetch(`/api/v1/sources/${encodeURIComponent(instance)}/discovery`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Infra-Sync-CSRF': 'same-origin' }, credentials: 'same-origin', body: '{}', signal, cache: 'no-store' }); }
  catch { throw new Error('Discovery worker is unavailable.'); }
  if (!response.ok) {
    let code = '';
    try { const value: unknown = await response.json(); code = record(value) && record(value.error) && typeof value.error.code === 'string' ? value.error.code : ''; } catch { /* safe fallback */ }
    throw new Error(code === 'SOURCE_DISABLED' ? 'Disabled sources cannot be discovered.' : code === 'DISCOVERY_TIMEOUT' ? 'Discovery timed out.' : 'Discovery failed. No changes were made.');
  }
  let value: unknown;
  try { value = await response.json(); } catch { throw new Error('Discovery returned malformed data.'); }
  if (!record(value) || value.source_instance !== instance || (value.source_type !== 'proxmox' && value.source_type !== 'esxi') || typeof value.site_slug !== 'string' || typeof value.cluster_name !== 'string' || !Array.isArray(value.items) || !value.items.every(item)) throw new Error('Discovery returned malformed data.');
  return value as unknown as DiscoveryResult;
}
