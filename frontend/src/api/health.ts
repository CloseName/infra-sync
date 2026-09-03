import type { SystemHealth } from '../types/health';

const statuses = new Set(['healthy', 'degraded', 'unavailable', 'unknown']);
const components = ['api', 'application', 'database', 'registry', 'netbox'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function validHealth(value: unknown): value is SystemHealth {
  if (!isRecord(value) || !statuses.has(String(value.status)) || !isRecord(value.components)) return false;
  const entries = value.components;
  return components.every((key) => {
    const item = entries[key];
    return isRecord(item) && statuses.has(String(item.status)) && typeof item.message === 'string'
      && (item.error_code === null || typeof item.error_code === 'string');
  });
}

export async function fetchHealth(signal: AbortSignal): Promise<SystemHealth> {
  const response = await fetch('/api/v1/system/health', { signal, cache: 'no-store' });
  if (!response.ok) throw new Error('Health API is unavailable. Please try again.');
  const data: unknown = await response.json();
  if (!validHealth(data)) throw new Error('Health API returned an unsupported response.');
  return data;
}
