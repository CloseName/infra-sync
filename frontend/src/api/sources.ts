export interface Source {
  source_instance: string;
  type: 'proxmox' | 'esxi';
  name: string;
  address: string;
  enabled: boolean;
  sync_enabled: boolean;
  verify_ssl: boolean;
  sync_interval_seconds: number;
  site_slug: string;
  cluster_name: string;
  platform_slug: string;
  device_role_slug: string;
  device_type_slug: string;
  cluster_type_slug: string;
  legacy_identity_owner: boolean;
  status: 'enabled' | 'disabled' | 'sync_disabled';
}

const textFields = ['source_instance', 'name', 'address', 'site_slug', 'cluster_name',
  'platform_slug', 'device_role_slug', 'device_type_slug', 'cluster_type_slug'];
const flags = ['enabled', 'sync_enabled', 'verify_ssl', 'legacy_identity_owner'];

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isSource(value: unknown): value is Source {
  return record(value) && textFields.every((key) => typeof value[key] === 'string' && value[key] !== '')
    && flags.every((key) => typeof value[key] === 'boolean')
    && (value.type === 'proxmox' || value.type === 'esxi')
    && typeof value.status === 'string' && ['enabled', 'disabled', 'sync_disabled'].includes(value.status)
    && typeof value.sync_interval_seconds === 'number'
    && Number.isSafeInteger(value.sync_interval_seconds) && value.sync_interval_seconds > 0;
}

async function request(path: string, signal: AbortSignal): Promise<unknown> {
  let response: Response;
  try { response = await fetch(path, { signal, cache: 'no-store' }); }
  catch { throw new Error('API unavailable. Check the connection and try again.'); }
  if (response.status === 404) throw new Error('Source not found. Refresh the source list.');
  if (response.status === 503) throw new Error('Registry or source metadata unavailable. Check System Health.');
  if (!response.ok) throw new Error('API unavailable. Try again.');
  try { return await response.json(); }
  catch { throw new Error('API returned a malformed response.'); }
}

export async function fetchSources(signal: AbortSignal): Promise<Source[]> {
  const data = await request('/api/v1/sources', signal);
  if (!record(data) || !Array.isArray(data.sources) || !data.sources.every(isSource)) {
    throw new Error('API returned a malformed source list.');
  }
  return data.sources;
}

export async function fetchSource(instance: string, signal: AbortSignal): Promise<Source> {
  const data = await request(`/api/v1/sources/${encodeURIComponent(instance)}`, signal);
  if (!isSource(data) || data.source_instance !== instance) throw new Error('API returned malformed source details.');
  return data;
}
