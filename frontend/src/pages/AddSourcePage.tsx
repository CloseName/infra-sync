import { useState } from 'react';
import type { FormEvent } from 'react';
import { cancelOnboarding, registerSource, testConnection } from '../api/onboarding';
import type { Source } from '../api/sources';

const fields = ['source_instance', 'name', 'site_slug', 'cluster_name', 'platform_slug',
  'device_role_slug', 'device_type_slug', 'cluster_type_slug'] as const;

export function AddSourcePage() {
  const [type, setType] = useState<'proxmox' | 'esxi'>('proxmox');
  const [connection, setConnection] = useState({ address: '', verify_ssl: true });
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<Source | null>(null);

  async function changeConnection() {
    if (busy) return;
    setBusy(true); setError('');
    try { await cancelOnboarding(token); setToken(''); }
    catch { setError('Could not invalidate the previous test. Retry before changing connection values.'); }
    finally { setBusy(false); }
  }

  async function test(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError('');
    try {
      const tokenValue = await testConnection({ source_type: type, ...connection,
        username: String(data.get('username')), secret: String(data.get('secret')),
        ...(type === 'proxmox' ? { token_id: String(data.get('token_id')) } : {}) });
      setToken(tokenValue);
    } catch { setError('Connection test failed. Re-enter credentials to retry; nothing was registered.'); }
    finally { form.reset(); setBusy(false); }
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (data.get('confirm') !== 'on') return;
    setBusy(true); setError('');
    try {
      const metadata = Object.fromEntries(fields.map((field) => [field, String(data.get(field))])) as
        Record<typeof fields[number], string>;
      const result = await registerSource({ ...metadata, source_type: type, ...connection,
        onboarding_token: token, sync_interval_seconds: Number(data.get('interval')), confirm_sync_disabled: true });
      setCreated(result);
    } catch { setError('Registration failed or outcome is uncertain. Ask the operator before retrying.'); }
    finally { setToken(''); setBusy(false); }
  }

  if (created) return <main><h1>Source registered</h1><p>Automatic synchronization is OFF.</p>
    <dl className="source-detail"><dt>Source instance</dt><dd>{created.source_instance}</dd>
      <dt>Address</dt><dd>{created.address}</dd><dt>Enabled</dt><dd>Yes</dd>
      <dt>Sync enabled</dt><dd>No</dd><dt>Status</dt><dd>{created.status}</dd></dl>
    <p>Credentials are protected. Connection was tested during onboarding, not continuously.</p></main>;

  return <main><h1>Add source</h1><p className="intro">Test connection, review metadata, then explicitly register.
    No discovery or synchronization will run.</p>
    {error && <p role="alert" className="source-error">{error}</p>}
    {!token ? <form onSubmit={test} className="source-form" autoComplete="off">
      <fieldset disabled={busy}>
      <label>Source type<select value={type} onChange={(event) => {
        const nextType = event.target.value as typeof type;
        event.currentTarget.form?.reset();
        setType(nextType);
      }}>
        <option value="proxmox">Proxmox</option><option value="esxi">VMware ESXi</option></select></label>
      <label>Hostname or IPv4 address<input required value={connection.address} pattern="[^/@%?#:\\\\ ]+"
        onChange={(event) => setConnection({ ...connection, address: event.target.value })} /></label>
      <label><input type="checkbox" checked={connection.verify_ssl}
        onChange={(event) => setConnection({ ...connection, verify_ssl: event.target.checked })} /> Verify TLS certificate</label>
      <label>{type === 'proxmox' ? 'Token user (user@realm)' : 'Username'}<input name="username" required /></label>
      {type === 'proxmox' && <label>Token name (without user prefix)<input name="token_id" type="password" required /></label>}
      <label>{type === 'proxmox' ? 'Token secret' : 'Password'}<input name="secret" type="password" required
        autoComplete="new-password" /></label>
      <button disabled={busy}>{busy ? 'Testing…' : 'Test Connection'}</button>
      </fieldset>
    </form> : <form onSubmit={register} className="source-form">
      <p>Connection test succeeded. Credentials have been cleared from the form.</p>
      <p>Review: {type} · {connection.address} · TLS verification {connection.verify_ssl ? 'on' : 'off'}.</p>
      <button type="button" disabled={busy} onClick={changeConnection}>
        Change connection and re-test
      </button>
      {fields.map((field) => <label key={field}>{field.replaceAll('_', ' ')}<input name={field} required maxLength={1024}
        pattern={field === 'source_instance' ? '[a-z0-9][a-z0-9._-]{1,62}' : undefined} /></label>)}
      <label>Configured interval (seconds)<input name="interval" type="number" min={1} max={2147483647}
        step={1} defaultValue={600} required /></label>
      <label><input name="confirm" type="checkbox" required /> Register a new source with automatic sync OFF.</label>
      <button disabled={busy}>{busy ? 'Registering…' : 'Register Source'}</button>
    </form>}
  </main>;
}
