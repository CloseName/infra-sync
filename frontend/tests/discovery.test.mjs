import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { runDiscovery } from '../src/api/discovery.ts';

const result = { source_instance: 'pve-test', source_type: 'proxmox', site_slug: 'test',
  cluster_name: 'Test', items: [{ object_kind: 'qemu', name: 'vm', external_id: '100',
    classification: 'IGNORED', reason_code: 'POLICY_FUTURE', reason: 'Visible ignored item',
    future_action: 'ignored', matched_object_id: null, matched_object_name: null }] };

test('discovery client sends protected POST and preserves visible classifications', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json(result));
  assert.deepEqual(await runDiscovery('pve-test', new AbortController().signal), result);
  const [path, options] = mock.mock.calls[0].arguments;
  assert.equal(path, '/api/v1/sources/pve-test/discovery');
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-NetBox-Sync-CSRF'], 'same-origin');
});

test('discovery client rejects malformed result and reports stable errors', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({ ...result,
    items: [{ ...result.items[0], classification: ['IGNORED'] }] }));
  await assert.rejects(runDiscovery('pve-test', new AbortController().signal), /malformed/);
  mock.mock.mockImplementation(async () => Response.json({ error: { code: 'SOURCE_DISABLED' } }, { status: 409 }));
  await assert.rejects(runDiscovery('pve-test', new AbortController().signal), /Disabled/);
});

test('source detail keeps discovery review separate from explicit sync controls', () => {
  const page = readFileSync(new URL('../src/pages/SourcesPage.tsx', import.meta.url), 'utf8');
  for (const text of ['Run discovery', 'Running read-only discovery', 'role="alert"',
    'Classification', 'Object kind', 'reason_code', 'summary-grid']) assert.ok(page.includes(text));
  assert.ok(page.includes('Build plan'));
  assert.ok(page.includes('Sync Now'));
  assert.ok(!page.includes('Apply changes'));
  assert.ok(classificationsVisibleInClient());
});

function classificationsVisibleInClient() {
  const client = readFileSync(new URL('../src/api/discovery.ts', import.meta.url), 'utf8');
  return client.includes("'IGNORED'") && client.includes("'UNSUPPORTED'");
}
