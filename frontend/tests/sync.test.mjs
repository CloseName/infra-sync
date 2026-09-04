import assert from 'node:assert/strict';
import test from 'node:test';
import { applySync, buildSyncPlan, prepareSync } from '../src/api/sync.ts';

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
    new AbortController().signal), /confirmation failed/);
  mock.mock.mockImplementation(async () => Response.json({ status: ['SUCCEEDED'],
    plan_digest: plan.digest }));
  await assert.rejects(applySync('pve-test', 'b'.repeat(64),
    new AbortController().signal), /did not complete/);
});
