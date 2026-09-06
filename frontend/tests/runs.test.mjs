import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fetchRuns, isSyncRun } from '../src/api/runs.ts';

const run = { run_id: '11111111-1111-4111-8111-111111111111', source_instance: 'pve-test',
  source_type: 'proxmox', trigger: 'manual', status: 'LOCKED',
  started_at: '2026-09-05T10:00:00Z', finished_at: '2026-09-05T10:00:01Z',
  duration_ms: 1000, plan_digest: 'a'.repeat(64), planner_version: 'web-5a-1',
  actions: { create: 2, update: 3, no_change: 4, review_required: 0, blocked: 0,
    ignored: 0, unsupported: 0, retain_only: 1 }, error_code: 'APPLY_LOCKED',
  error_message_safe: 'Another synchronization is already running.', created_by: 'web/manual' };

test('history client validates safe list data and rejects malformed payloads', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({ runs: [run], next_cursor: null }));
  assert.deepEqual(await fetchRuns(new AbortController().signal), [run]);
  mock.mock.mockImplementation(async () => Response.json({ runs: [{ ...run, status: ['LOCKED'] }] }));
  await assert.rejects(fetchRuns(new AbortController().signal), /History could not be loaded/);
  assert.equal(isSyncRun({ ...run, actions: { ...run.actions, create: -1 } }), false);
  assert.equal(isSyncRun({ ...run, started_at: 'not-a-time' }), false);
  assert.equal(isSyncRun({ ...run, plan_digest: 'short' }), false);
  assert.equal(isSyncRun({ ...run, run_id: '------------------------------------' }), false);
});

test('history failures never expose raw backend messages', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({
    error: { code: 'INTERNAL', message: 'password=secret https://private.invalid' },
  }, { status: 503 }));
  await assert.rejects(fetchRuns(new AbortController().signal),
    (error) => error.message === 'History could not be loaded.');
});

test('history page includes loading empty table detail and safe error states', () => {
  const page = readFileSync(new URL('../src/pages/RunsPage.tsx', import.meta.url), 'utf8');
  for (const text of ['Loading history...', 'No synchronization runs recorded yet.',
    'History could not be loaded.', 'Run details', 'Source type', 'Trigger', 'Changes',
    'Plan digest', 'Review required', 'error_message_safe']) assert.ok(page.includes(text));
  assert.ok(page.includes('runPath(run.run_id)'));
});
