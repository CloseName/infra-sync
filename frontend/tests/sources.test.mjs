import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchSource, fetchSources, isSource } from '../src/api/sources.ts';

const source = {
  source_instance: 'pve-test', type: 'proxmox', name: 'Test', address: 'pve.example.test',
  enabled: true, sync_enabled: true, verify_ssl: true, sync_interval_seconds: 600,
  site_slug: 'test', cluster_name: 'Test', platform_slug: 'pve', device_role_slug: 'host',
  device_type_slug: 'server', cluster_type_slug: 'pve', legacy_identity_owner: true, status: 'enabled',
};

test('source response validation rejects malformed fields', () => {
  assert.ok(isSource(source));
  for (const changes of [{ enabled: 'true' }, { type: 'other' }, { status: 'healthy' },
    { sync_interval_seconds: 0 }, { site_slug: null }]) {
    assert.equal(isSource({ ...source, ...changes }), false);
  }
});

test('source status accepts only supported strings', () => {
  for (const status of ['enabled', 'disabled', 'sync_disabled']) {
    assert.equal(isSource({ ...source, status }), true);
  }
  for (const status of [['enabled'], {}, 1, true, false, null, undefined, 'healthy', '']) {
    assert.equal(isSource({ ...source, status }), false);
  }
});

test('list/detail clients reject array status before rendering', async (context) => {
  const signal = new AbortController().signal;
  const malformed = { ...source, status: ['enabled'] };
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({ sources: [malformed] }));
  await assert.rejects(fetchSources(signal), /malformed source list/);
  mock.mock.mockImplementation(async () => Response.json(malformed));
  await assert.rejects(fetchSource('pve-test', signal), /malformed source details/);
});

test('list/detail clients validate payloads and errors', async (context) => {
  const signal = new AbortController().signal;
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({ sources: [source] }));
  assert.deepEqual(await fetchSources(signal), [source]);
  mock.mock.mockImplementation(async () => Response.json({ sources: [] }));
  assert.deepEqual(await fetchSources(signal), []);
  mock.mock.mockImplementation(async () => Response.json(source));
  assert.deepEqual(await fetchSource('pve-test', signal), source);
  await assert.rejects(fetchSource('other-source', signal), /malformed/);
  mock.mock.mockImplementation(async () => Response.json({ sources: [{}] }));
  await assert.rejects(fetchSources(signal), /malformed/);
  mock.mock.mockImplementation(async () => new Response('SECRET', { status: 503 }));
  await assert.rejects(fetchSources(signal), /Registry or source metadata unavailable/);
  mock.mock.mockImplementation(async () => new Response('SECRET', { status: 404 }));
  await assert.rejects(fetchSource('missing', signal), /Source not found/);
  mock.mock.mockImplementation(async () => { throw new Error('SECRET'); });
  await assert.rejects(fetchSources(signal), /API unavailable/);
});
