import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { applySync, buildSyncPlan, prepareSync, resultForSource } from '../src/api/sync.ts';

const plan = { source_instance: 'pve-test', source_type: 'proxmox',
  source_fingerprint: 'a', target_fingerprint: 'b', provider_fingerprint: 'c', netbox_fingerprint: 'd',
  schema_version: 1, planner_version: 'web-5a-1', apply_allowed: true,
  digest: 'a'.repeat(64), items: [{ object_kind: 'qemu', external_id: '1', name: 'vm',
    action: 'NO_CHANGE', reason_code: 'MATCH', reason: 'match', matched_object_id: 1,
    before: [], after: [] }] };

test('sync plan client uses protected POST and validates canonical response', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json(plan));
  assert.deepEqual(await buildSyncPlan('pve-test', new AbortController().signal), plan);
  const [, options] = mock.mock.calls[0].arguments;
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-Infra-Sync-CSRF'], 'same-origin');
});

test('sync plan rejects malformed action and digest', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ ...plan,
    items: [{ ...plan.items[0], action: ['NO_CHANGE'] }] }));
  await assert.rejects(buildSyncPlan('pve-test', new AbortController().signal), /malformed/);
});

test('confirmation and apply clients reject malformed worker capabilities', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () =>
    Response.json({ confirmation_token: ['not-a-token'] }));
  await assert.rejects(prepareSync('pve-test', plan.digest,
    new AbortController().signal), /No automatic retry/);
  mock.mock.mockImplementation(async () => Response.json({ status: ['SUCCEEDED'],
    plan_digest: plan.digest }));
  await assert.rejects(applySync('pve-test', 'b'.repeat(64),
    new AbortController().signal), /No automatic retry/);
});

test('manual sync maps stable API errors to safe operator-visible messages', async (context) => {
  const cases = [
    [409, 'APPLY_LOCKED', 'Manual sync could not start: another sync is already running. No changes were made.'],
    [409, 'PLAN_STALE', 'The sync plan is no longer current. Build a new plan before syncing.'],
    [503, 'OUTCOME_UNCERTAIN', 'Manual sync stopped after the write phase began. The final NetBox state may be uncertain; review the source before retrying.'],
  ];
  const mock = context.mock.method(globalThis, 'fetch');
  for (const [status, code, message] of cases) {
    mock.mock.mockImplementationOnce(async () => Response.json({ error: { code, message: 'ignored raw backend text' } }, { status }));
    await assert.rejects(applySync('pve-test', 'b'.repeat(64),
      new AbortController().signal), (error) => error.message === message);
  }
});

test('manual sync success remains explicit and unknown failures are generic', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({
    status: 'SUCCEEDED', plan_digest: plan.digest,
  }));
  assert.equal(await applySync('pve-test', 'b'.repeat(64),
    new AbortController().signal), 'SUCCEEDED: Manual sync completed successfully.');
  mock.mock.mockImplementation(async () => Response.json({
    error: { code: 'UNRECOGNIZED', message: 'raw internal detail https://secret.invalid' },
  }, { status: 500 }));
  await assert.rejects(applySync('pve-test', 'b'.repeat(64),
    new AbortController().signal), /Manual sync request failed\. No automatic retry was performed\./);
});

test('sync result remains rendered after busy state releases the button', () => {
  const page = readFileSync(new URL('../src/pages/SourcesPage.tsx', import.meta.url), 'utf8');
  assert.ok(page.includes("setSyncResult({ sourceInstance: selected, kind: 'error'"));
  assert.ok(page.includes("setSyncResult({ sourceInstance: selected, kind: 'success'"));
  assert.ok(page.includes('finally { setSyncing(false); }'));
  assert.ok(page.includes("role={visibleSyncResult.kind === 'error' ? 'alert' : 'status'}"));
  assert.ok(!page.includes('finally { setSyncResult(null)'));
});

test('manual sync outcomes are visible only for their source instance', () => {
  const lockedA = { sourceInstance: 'source-a', kind: 'error',
    message: 'Manual sync could not start: another sync is already running. No changes were made.' };
  const successB = { sourceInstance: 'source-b', kind: 'success', message: 'SUCCEEDED' };
  assert.equal(resultForSource(lockedA, 'source-a'), lockedA);
  assert.equal(resultForSource(lockedA, 'source-b'), null);
  assert.equal(resultForSource(successB, 'source-a'), null);
  assert.equal(resultForSource(successB, 'source-b'), successB);
});

test('source navigation explicitly clears any previous manual sync outcome', () => {
  const page = readFileSync(new URL('../src/pages/SourcesPage.tsx', import.meta.url), 'utf8');
  assert.ok(page.includes('setSelected(null); setDiscovery(null); setSyncPlan(null); setSyncResult(null);'));
  assert.ok(page.includes('setSyncResult(null); setSelected(source.source_instance);'));
});

test('application header uses a phase-neutral label', () => {
  const main = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.ok(main.includes('INFRA SYNC · SOURCE CONTROL'));
  assert.ok(!main.includes('SOURCE ONBOARDING · WEB-3'));
});
