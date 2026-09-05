import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fetchSchedule, isSchedule, updateSchedule } from '../src/api/schedule.ts';

const schedule = { source_instance: 'pve-test', sync_enabled: true,
  sync_interval_seconds: 600, scheduler_state: 'WAITING',
  last_scheduled_run_at: '2026-09-05T12:00:00Z',
  next_expected_at: '2026-09-05T12:10:00Z' };

test('schedule client validates all closed states and malformed values', () => {
  for (const scheduler_state of ['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED'])
    assert.equal(isSchedule({ ...schedule, scheduler_state }), true);
  for (const scheduler_state of [['WAITING'], 'UNKNOWN', null])
    assert.equal(isSchedule({ ...schedule, scheduler_state }), false);
});

test('schedule read and protected update use exact source and expected values', async (context) => {
  const signal = new AbortController().signal;
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json(schedule));
  assert.deepEqual(await fetchSchedule('pve-test', signal), schedule);
  const update = { sync_enabled: false, sync_interval_seconds: 300,
    expected_sync_enabled: true, expected_sync_interval_seconds: 600 };
  mock.mock.mockImplementation(async (_path, options) => {
    assert.equal(options.method, 'PATCH');
    assert.deepEqual(JSON.parse(options.body), update);
    return Response.json({ ...schedule, sync_enabled: false, sync_interval_seconds: 300,
      scheduler_state: 'DISABLED', next_expected_at: null });
  });
  assert.equal((await updateSchedule('pve-test', update, signal)).scheduler_state, 'DISABLED');
});

test('schedule errors are allowlisted and source page keeps manual controls', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({
    error: { code: 'SCHEDULE_CONFLICT', message: 'RAW SECRET', request_id: 'id' },
  }, { status: 409 }));
  await assert.rejects(updateSchedule('pve-test', {}, new AbortController().signal),
    /Scheduling settings changed since this page was loaded/);
  mock.mock.mockImplementation(async () => new Response('RAW DATABASE SECRET', { status: 503 }));
  await assert.rejects(fetchSchedule('pve-test', new AbortController().signal),
    /Scheduling request failed/);
  const page = readFileSync(new URL('../src/pages/SourcesPage.tsx', import.meta.url), 'utf8');
  for (const text of ['Automatic synchronization', 'Edit schedule', 'Custom seconds',
    'Manual synchronization remains available.', 'Build plan', 'Sync Now',
    'Credentials and source identity are protected. Scheduling can be edited below.',
    'Automatic synchronization updated.']) assert.ok(page.includes(text));
  for (const state of ['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED'])
    assert.equal(isSchedule({ ...schedule, scheduler_state: state }), true);
});
