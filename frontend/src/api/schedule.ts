export type SchedulerState = 'DISABLED' | 'WAITING' | 'DUE' | 'RUNNING' | 'DELAYED';
export interface Schedule { source_instance: string; sync_enabled: boolean; sync_interval_seconds: number; scheduler_state: SchedulerState; last_scheduled_run_at: string | null; next_expected_at: string | null; }
export interface ScheduleUpdate { sync_enabled: boolean; sync_interval_seconds: number; expected_sync_enabled: boolean; expected_sync_interval_seconds: number; }

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const time = (value: unknown) => value === null || (typeof value === 'string' && !Number.isNaN(Date.parse(value)));
export const isSchedule = (value: unknown): value is Schedule => record(value)
  && typeof value.source_instance === 'string' && typeof value.sync_enabled === 'boolean'
  && Number.isSafeInteger(value.sync_interval_seconds) && Number(value.sync_interval_seconds) > 0
  && typeof value.scheduler_state === 'string' && ['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED'].includes(value.scheduler_state)
  && time(value.last_scheduled_run_at) && time(value.next_expected_at);

const safeErrors: Record<string, string> = {
  SCHEDULE_INVALID: 'Choose an interval between 60 seconds and 24 hours.',
  SCHEDULE_CONFLICT: 'Scheduling settings changed since this page was loaded. Refresh and try again.',
  SOURCE_NOT_FOUND: 'Source not found. Refresh the source list.',
  CONTROL_WORKER_UNAVAILABLE: 'Scheduling control is unavailable.',
  CONTROL_REQUEST_FAILED: 'Scheduling update failed.',
  SCHEDULE_UNAVAILABLE: 'Scheduling state is unavailable.',
};
async function parse(response: Response, instance: string): Promise<Schedule> {
  if (!response.ok) {
    let value: unknown; try { value = await response.json(); } catch { throw new Error('Scheduling request failed.'); }
    const code = record(value) && record(value.error) && typeof value.error.code === 'string' ? value.error.code : '';
    throw new Error(safeErrors[code] ?? 'Scheduling request failed.');
  }
  let value: unknown; try { value = await response.json(); } catch { throw new Error('Scheduling request failed.'); }
  if (!isSchedule(value) || value.source_instance !== instance) throw new Error('Scheduling request failed.');
  return value;
}
export async function fetchSchedule(instance: string, signal: AbortSignal) {
  let response: Response; try { response = await fetch(`/api/v1/sources/${encodeURIComponent(instance)}/schedule`, { signal, cache: 'no-store' }); } catch { throw new Error('Scheduling request failed.'); }
  return parse(response, instance);
}
export async function updateSchedule(instance: string, update: ScheduleUpdate, signal: AbortSignal) {
  let response: Response; try { response = await fetch(`/api/v1/sources/${encodeURIComponent(instance)}/schedule`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-Infra-Sync-CSRF': 'same-origin' }, credentials: 'same-origin', cache: 'no-store', signal, body: JSON.stringify(update) }); } catch { throw new Error('Scheduling request failed.'); }
  return parse(response, instance);
}
