# WEB-3: protected source onboarding, health and source visibility

## WEB-3 security boundary

WEB-3 adds only Test Connection and explicit registration of a new source. It
does not enable sync, update/delete existing sources, adopt inventory, run
discovery or change the systemd scheduler. Existing WEB-1/2 read paths remain.
The sections below describing read-only WEB-1/2 behavior apply to those endpoints;
onboarding writes have the separate privileges and restrictions in this section.

### Flow and request contracts

1. Choose Proxmox or ESXi; enter a bare hostname/IPv4 address and verify_ssl.
2. Enter Proxmox user@realm, token name (without user prefix), token secret;
   or ESXi username/password. No URL, port or path is accepted for WEB-3 inputs:
   this preserves the existing bare-host runtime connection contract. Existing
   registered sources and WEB-2 address display are not modified.
3. POST /api/v1/sources/test-connection authenticates and reads only Proxmox
   version or ESXi service content. ESXi uses an ephemeral authenticated SOAP
   session (HTTP POST for login/read/logout), not inventory mutation. Connect/read
   timeouts are five seconds; an isolated non-root child is killed and reaped after
   a 15-second whole-operation deadline, including DNS and the initial version GET.
   No registry/broker write occurs. No NetBox call occurs.
4. A successful test returns an unpredictable onboarding_token, valid for ten
   minutes and one registration attempt. Credentials remain in bounded
   process-local memory only (maximum 128 pending items); expiry timers discard
   them. The form clears credentials when the test settles. All connection fields
   are disabled in flight. Change connection calls POST /api/v1/sources/cancel-onboarding
   with the opaque token, revokes its server-side credential handoff, clears the browser
   token, and requires a new test. Cancellation uses the same Host/Origin/CSRF boundary,
   is idempotent, and does not call the registry or broker. No browser storage is used.
5. Review source_instance, name, site_slug, cluster_name, platform_slug,
   device_role_slug, device_type_slug, cluster_type_slug, verify_ssl and
   sync_interval_seconds. Confirm automatic synchronization stays disabled.
6. POST /api/v1/sources includes this metadata, source_type/address bound to the
   tested connection, onboarding_token, and confirm_sync_disabled=true. Backend
   revalidates it. Success is HTTP 201 with only the existing safe SourceDTO.

Defaults are enforced server-side: enabled=true, sync_enabled=false,
legacy_identity_owner=false, settings={}. Callers cannot override them.
Duplicate source_instance is HTTP 409 SOURCE_ALREADY_EXISTS, never an upsert.
Token replay/expiry is ONBOARDING_TOKEN_INVALID/409. Failed registrations consume
the token; retest only after reviewing any uncertain outcome. A successful test
is historical evidence, not continuing source health or permission to sync.

Credentials with leading/trailing whitespace are rejected because the existing
file resolver strips whitespace. Proxmox uses two file references; ESXi uses the
same password file reference for token_id and token_secret as SourceCredentials
already supports. Username remains in the existing registry username column,
which the existing runtime requires; password/token material remains only in
protected files. Username and references are never in public DTOs. Credential
container repr() is suppressed, without changing runtime fields or resolution.

### Root broker, socket and mounts

The opt-in infra-sync-secret-broker service runs UID/GID 0:0, supplementary GID
10001, with cap_drop ALL, no-new-privileges, read-only root filesystem and
network_mode=none. Its only mounts are the dedicated source-secret directory and
the shared Unix-socket volume. It has no TCP listener and no Docker socket.

The Web/API remains UID 10001, cap_drop ALL, no-new-privileges and read-only. It
receives only the socket volume read-only, not the source-secret directory.
The socket is root:10001 mode 0660, in a root-owned directory not writable by
group/others. Linux SO_PEERCRED must identify UID 10001 before a request is read.
The broker uses the supplementary group to set socket ownership without adding
CAP_CHOWN. Container smoke tests exercise this exact restriction.

Only create and rollback requests exist. There is no read/list endpoint. Clients
send a logical key, never a filesystem path. Keys must match
`^[A-Za-z0-9][A-Za-z0-9_-]{15,127}$`: no dots, slashes, backslashes or percent
encoding. Onboarding generates src-<normalized-instance>-<kind>-<random-hex> keys.
References remain SecretReference(provider='file', key=<flat-logical-name>).

The configured secret root must be an absolute root:root 0700 directory. Every
directory component is opened with O_DIRECTORY/O_NOFOLLOW. File creation uses
dir_fd, O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600, root:root, bounded 4096-byte values,
complete writes, fsync(file), and fsync(directory) before success. Existing files
are never overwritten. No plaintext broker payloads are logged.

Rollback requires the exact operation ID, logical key and random receipt from
creation. These are stored as root-protected user.infra_sync.* extended file
attributes, together with a completion marker, fsynced before acknowledging.
Rollback checks the receipt, operation, owner, mode, regular-file/link status and
open-descriptor/path inode consistency immediately before unlink. Failed-create
cleanup checks the created inode and all successfully written attempt xattrs too.
The filesystem must support user extended attributes; unsupported
storage fails closed. Secret contents and runtime reference formats are unchanged.
A same-operation create retry can recover its durable receipt without overwriting
content. The client retries once with the same operation/key after transport
failure; broker restart does not erase completed-file ownership evidence.

The broker holds nonblocking exclusive flock locks on the secret-root and socket
directory inodes before binding. A second broker sharing either directory fails
startup without replacing the live socket. The directory must have no other writer:
do not modify it from the host while onboarding is active. Python/Linux has no
portable unlink-by-descriptor primitive; a privileged external writer could still
race the final stat/unlink or copy receipt xattrs onto a replacement. This is not
claimed to protect against a hostile host administrator. Read requests have an
absolute five-second receive deadline, not a resettable per-byte budget.

### Failure and reconciliation policy

Secret creation must finish before INSERT. A failed secret step rolls back only
earlier successful creations from that attempt; no registry INSERT is attempted.
A definitely rejected SQL statement rolls back only this attempt's receipts.
A separate adapter transaction boundary encloses INSERT, fetch and commit.
Returned-row/domain conversion occurs outside that boundary. Any conversion error,
including ValueError/TypeError, triggers reconciliation, never definite rollback.
A connection/commit uncertainty triggers an exact source_instance lookup using
the writer connection. If the full stored configuration matches, registration
is treated as committed. Otherwise—including a failed lookup or an absent row
after an uncertain commit—secrets are retained and REGISTRATION_UNCERTAIN/503 is
returned. An absent row alone does not prove that a delayed commit cannot occur.
Rollback failure is also reported as uncertain, never silently successful.

There is no distributed transaction between PostgreSQL and the filesystem.
Process crashes during an incomplete file write, or loss of the API process's
attempt context, can leave an unreferenced secret. No broad cleanup is implemented.
Operators must reconcile exact registry
references before handling these files. Do not delete a file merely because the
browser reported failure. Durable completed-file receipts support safe retries,
but automatic background recovery after API crashes is not claimed by WEB-3.

### Database permissions (operator-only; never executed at startup)

Keep INFRA_SYNC_REGISTRY_DSN on the WEB-2 SELECT-only role unchanged. Supply a
separate INFRA_SYNC_REGISTRATION_DSN only for registration. The writer checks
schema_version=1 and reuses SourceRegistry's canonical validation/encoding/decoding
with an explicit adapter-owned INSERT transaction, never initialize(), migrations,
UPDATE, DELETE or UPSERT. Existing runtime SourceRegistry semantics are unchanged.

The writer role needs CONNECT on the database, USAGE on the registry schema,
SELECT(key,value) on schema_meta, SELECT on sources (the writer retains RETURNING *
and existing reconciliation uses SELECT * to load SourceConfig), and INSERT on these columns:

```text
id, source_instance, name, source_type, address, enabled, sync_enabled,
sync_interval_seconds, verify_ssl, site_slug, device_role_slug, platform_slug,
device_type_slug, cluster_type_slug, cluster_name, username, token_id_provider,
token_id_key, token_secret_provider, token_secret_key, legacy_identity_owner, settings
```

No sequence grants are needed (IDs are text). No UPDATE, DELETE, TRUNCATE, schema
CREATE, ownership, role administration or migration rights should be granted.
Review inherited/PUBLIC privileges separately. The reader gets no new grants.
These privileges narrow the writer, but do not enforce new-source flag defaults
against a compromised writer credential; those defaults are application policy.

### Operator deployment steps — not performed by this change

- Prepare /opt/infra-sync/secrets/sources outside the repository, root:root 0700.
  Set INFRA_SYNC_SOURCE_SECRET_DIR to that absolute directory. Do not chmod
  existing unrelated secrets. Compose defaults are development paths only.
  Host root:root ownership assumes rootful Docker without UID remapping; verify
  actual host ownership and extended-attribute support before enabling the broker.
  xattrs are mandatory: operator storage preflight must exercise create/setxattr/
  getxattr/fsync/rollback on this dedicated filesystem before enabling onboarding.
- Provide the isolated writer DSN through protected configuration; do not print
  or commit it. Docker administrators can inspect container environment.
- Start the web and onboarding profiles in the same Compose project. No broker
  dependency is added to the existing scheduler; registration fails safely if
  broker/writer configuration is absent. Read-only views still work.
- Preserve loopback publication (production uses INFRA_SYNC_WEB_PORT=8001).
  Set INFRA_SYNC_WRITE_HOSTS to exact browser-visible host:port values, including
  the chosen SSH tunnel endpoint, e.g. 127.0.0.1:18001. Do not use wildcards.
  For Vite development, explicitly allow the browser's 127.0.0.1:5173 authority;
  the default 8000 allowlist is for direct API-served frontend access.
- Apply the reviewed compose.yml directory mount during deployment: the same
  INFRA_SYNC_SOURCE_SECRET_DIR is mounted read-only at /run/secrets/infra-sync-sources in
  the runtime, read-write in the broker, and never in the API. Existing individual
  mounts remain, including /run/secrets/infra-sync/esxi_infra_sync_password. A Docker
  smoke test found that a read-only parent mount cannot create the absent legacy
  child mountpoint, so the dedicated directory uses a separate sibling path.
  FileSecretResolver retains /run/secrets/infra-sync as its first lookup and falls
  back to the new directory only for a missing file, never for permission/validation
  errors. Custom resolver roots stay isolated unless a fallback is explicitly supplied.
  Both use identical flat logical references; do not rename old keys. New sources
  remain sync_disabled. No live deployment is performed by this change.

### Unauthenticated write protection and limitations

Writes require an allowlisted Host, matching Origin scheme/authority,
X-Infra-Sync-CSRF: same-origin, JSON content type, bounded Content-Length and a
same-origin/none Sec-Fetch-Site value when present. No permissive CORS is enabled.
The custom header forces cross-origin browser preflight; Origin/Host checks reject
cross-site requests even if a caller bypasses preflight. This is not user
authentication: local non-browser callers can forge headers. Keep the service
loopback/SSH-only and restrict local host access. Do not publish it externally.

### Mandatory onboarding egress policy

Only ASCII bare hostnames/canonical IPv4 inputs are accepted. Protocol/port are
fixed to HTTPS/8006 (Proxmox) or HTTPS/443 (ESXi). No redirects are followed by
either adapter. The Proxmox probe is a narrow http.client GET, not proxmoxer.

Defaults permit RFC1918 destinations; public endpoints require operator allowlisting.
Loopback, link-local/metadata, unspecified, multicast, reserved and other special-use
addresses remain denied even when allowlisted. Single-label/container-local names
require an exact hostname allow entry. Normal internal DNS names resolving only to
approved private IPs work by default. Operator variables are comma-separated:

- INFRA_SYNC_ONBOARDING_ALLOWED_CIDRS
- INFRA_SYNC_ONBOARDING_DENIED_CIDRS
- INFRA_SYNC_ONBOARDING_ALLOWED_HOSTS
- INFRA_SYNC_ONBOARDING_ALLOWED_SUFFIXES

Any nonempty allow configuration becomes a restriction: every answer must match an
allowed CIDR or the approved hostname/suffix. Denied CIDRs always win. Prefer narrow
CIDRs/exact hostnames; allowlisting a public hostname authorizes its public DNS answers.
The broker has no egress; these variables apply only to the Test Connection child.

DNS is resolved once, every answer is checked, and one approved IPv4 answer is pinned
for every subsequent socket lookup in the isolated child. Original hostname/SNI and
certificate verification are preserved. No proxy environment is inherited; alternate
host/port lookups fail. IPv6-only endpoints are unsupported. DNS rebinding cannot
switch to a newly resolved address within this attempt. Network routing and operator
allowlist correctness remain deployment responsibilities.

The short-lived probe child inherits UID10001 and container hardening, but not registry
DSNs or broker configuration. Credentials travel through stdin, never argv/environment.
Dependency logging is disabled only in that child; stderr is discarded, stdout is a
small allowlisted result, and HTTP wire debugging is disabled. Parent/operator logs
are unchanged. The 15-second parent deadline covers DNS, all TLS/HTTP/SOAP calls and
logout; forced termination can leave a remote session until the server expires it.
No live connection tests are part of the mandatory suite. Do not enable core dumps;
Python does not guarantee zeroization of immutable strings.

Onboarding state is process-local: use the current single-worker startup.
Restarts invalidate pending tokens. There is no source editing, rotation, delete,
Sync Now, adoption, discovery UI, authentication or scheduler change. Future
WEB-4 should address durable onboarding recovery, authentication and full browser
workflow coverage before broadening deployment or write functionality.

The optional Web/API shell does not execute discovery, plans or sync. Existing
CLI execution, registry-all selection, identities, confirmations and systemd are
unchanged. Only file-secret lookup gains the compatible missing-file fallback.
No production cutover or migration is part of this change.

## Boundaries

`api/app.py` constructs FastAPI and maps application results to explicit frozen
Pydantic DTOs. `application/health.py` owns transport-neutral status aggregation
and accepts an injectable registry probe. `api/database.py` implements that port
with psycopg. Environment is read once by `api/settings.py` at factory bootstrap,
never mutated by requests. Neither routes nor health checks invoke sync helpers.

`frontend/src/` separates `api`, `types`, `components` and `pages`. React with
strict TypeScript fetches real health data on load or manual refresh; there is no
polling, fake inventory or action control. Failure replaces stale status with an
explicit error. Requests use a relative URL and a 15-second browser timeout.

## Endpoints and status semantics

| GET endpoint | Purpose |
|---|---|
| `/api/v1/health` | Cheap process liveness; no database connection |
| `/api/v1/system/health` | API, application, database, registry, NetBox configuration and overall status |
| `/api/v1/version` | Installed package version, without Git; `development` if not installed |

The system endpoint returns HTTP 200 when it successfully produces a report,
even when the report says `unavailable`. Container health uses liveness, not
external dependency readiness. Status values are `healthy`, `degraded`,
`unavailable` and `unknown`.

Database checks use SELECT 1, registry schema_version=1, and a LIMIT 0 projection
of non-secret source columns. They do not fetch source records or credential
references. Connections enforce read-only transactions, a 3-second connection
timeout and 2-second statement timeout. These are per-operation limits, not an
absolute request deadline (especially with multi-host DSNs).

An existing unbaselined registry v1 is readable: Alembic is neither required nor
invoked. Empty/missing/incompatible registry schemas report unavailable; no
tables are created or repaired. This is a basic readability check, not a full
constraint/schema audit. Database and registry failures use REGISTRY_UNAVAILABLE;
a readable database with an unreadable registry is reported separately.

NetBox is always `unknown`: only the presence of URL and token/token-file
configuration is checked, without opening a secret file or making a request.
Overall `healthy` means database/registry readable and NetBox configuration
present, NOT successful NetBox authentication, source connectivity or sync.
Missing database configuration or incomplete NetBox configuration is degraded;
an unavailable database/registry makes overall status unavailable.

Transport errors use `error: {code, message, request_id}` with fixed safe messages.
Unknown exceptions return API_INTERNAL_ERROR, never exception text. Each request
gets a fresh server UUID in X-Request-ID; client IDs are not reflected. JSON API
logs include component=api and request_id; run_id and source_instance remain null
because no run occurs. Paths, query strings, payloads and raw errors are not logged.
Use the documented `--no-access-log` flag to prevent separate Uvicorn URL logs.

## Local development

From the repository root, using Python 3.12 or 3.13:

```sh
python -m pip install -e ".[web]"
python -m pip install -r requirements-dev.txt
uvicorn netbox_pve_sync.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal (Node 24 is used by Dockerfile.web):

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to localhost:8000. Production assets
use the same origin as FastAPI, with no CORS middleware or wildcard origins.

```sh
npm run typecheck
npm run build
```

To serve the built shell locally, set INFRA_SYNC_WEB_DIST to the absolute
`frontend/dist` directory before starting FastAPI. Only its index and assets are
served; there is no arbitrary file browser or SPA catch-all.

## Configuration

| Variable | Use |
|---|---|
| INFRA_SYNC_REGISTRY_DSN | Existing registry connection convention; optional for degraded local startup; secret, never print it |
| INFRA_SYNC_REGISTRY_SCHEMA | Existing registry schema convention; required for a configured registry |
| NB_API_URL | Presence-only NetBox configuration signal |
| NB_API_TOKEN / NB_API_TOKEN_FILE | Either counts as configuration present; neither resolved or returned |
| INFRA_SYNC_WEB_DIST | Optional new API static-build directory; preset in Web image |
| INFRA_SYNC_WEB_PORT | Optional new Compose loopback port, default 8000 |

Use a dedicated read-only PostgreSQL role with schema USAGE and SELECT access to
schema_meta and the queried sources columns. Do not grant migration/registry
write permissions. The API does not need source or NetBox secret mounts.

## Optional Compose role

```sh
docker compose -f compose.yml -f compose.web.yml --profile web up -d --build infra-sync-api
```

Use the same existing Compose project name/configuration. Legacy compose.yml
still requires its existing environment values at interpolation time. For an
isolated local API-only check, `-f compose.web.yml --profile web` works alone;
this is not a second production stack or scheduler.

Dockerfile.web builds React assets and installs the optional web extra into the
same Python package. FastAPI serves the assets; no separate frontend container
or Redis is needed. The existing CLI Dockerfile is deliberately unchanged; a
shared deployed API/worker image is a future approved transition.

The API binds a host loopback port, runs non-root with read-only root filesystem,
dropped capabilities and a temporary /tmp. Healthcheck reads liveness only.
Compose forwards existing registry configuration and NetBox URL/token-file
presence (not token contents), and mounts no secrets. It does not create a DB,
change PostgreSQL healthchecks, or attach to production networks automatically.
Arrange private connectivity to the existing PostgreSQL endpoint using the
operator's actual network configuration; localhost inside a container is not
the host database. Never run migrations as part of API startup.

## Validation and limitations

```sh
pytest -q
pylint --fail-under=9.0 --max-line-length=120 netbox_pve_sync
git diff --check
python -m build --wheel
```

API tests use injected fake connections, not production services. Existing
PostgreSQL/live ESXi integration tests remain opt-in. Frontend validation is
strict type-check plus production build; browser automation is not yet added.

Authentication is intentionally absent. Keep this API on loopback or a trusted
private access path; do not publish it directly to the Internet. No write API,
source CRUD, secret management, Sync Now, Plan, queue, worker, scheduler, or run
history is implemented. Reverse-proxy authentication/rate limiting/log policy
and production image/network validation remain deployment gates.

## WEB-2 source visibility

The shell has System Health and Sources navigation using local React state, not
a new routing/state framework. Refresh returns to System Health; source selection
is not a persistent URL. List and details fetch real API data with a 15-second
browser timeout, loading, empty and safe error states. No source connection test
is performed. Credentials are not loaded; no editing controls exist.

| GET endpoint | Response |
|---|---|
| `/api/v1/sources` | `{ "sources": [...] }`, including an empty list |
| `/api/v1/sources/{source_instance}` | One source DTO, exact instance match |

Both use the same explicit projection:

```text
source_instance, type, name, address, enabled, sync_enabled, verify_ssl,
sync_interval_seconds, site_slug, cluster_name, platform_slug, device_role_slug,
device_type_slug, cluster_type_slug, legacy_identity_owner, status
```

Target values are configured slugs/names, not live-resolved NetBox objects.
`type` maps from the `source_type` database column; `status` is derived, not stored:
disabled when enabled=false; sync_disabled when enabled=true and sync_enabled=false;
otherwise enabled. No status claims health/authentication. The configured interval
is not evidence that the existing systemd scheduler enforces per-source intervals.

SourceVisibilityService maps to immutable SourceView objects. PostgresSourceReader
selects only the 15 stored fields above (source_type instead of type; no status).
It never selects id, username, token_id_provider, token_id_key,
token_secret_provider, token_secret_key, settings, created_at or updated_at.
No SourceRegistry objects, credential resolvers, initialize calls or Alembic are
used in the read path. The registry version check and source query execute in a
read-only transaction with the same configuration and timeouts as WEB-1.

The API returns SOURCE_NOT_FOUND/404 for absent or invalid instance identifiers,
REGISTRY_UNAVAILABLE/503 for missing configuration, invalid schema, unsupported
registry version or database errors, and SOURCE_DATA_INVALID/503 for malformed
public metadata. Envelopes include the server-generated request ID; no driver
messages or queried instance strings are included in error messages/logs.

Addresses containing userinfo, query strings, fragments, encoded characters or
non-root paths are rejected rather than exposing potential credentials. This
conservative policy can reject a valid path-based endpoint: correct the public
address design before relaxing it. No generic sanitizer can detect a secret
deliberately stored as a display name or hostname; public metadata fields must
not be used to store credentials. An invalid row fails the complete list closed.
There is no pagination yet; intended for the existing small registry.

## Registry access and production viewing

compose.web.yml remains unchanged: supply INFRA_SYNC_REGISTRY_DSN and
INFRA_SYNC_REGISTRY_SCHEMA through the operator's protected environment/.env
configuration. Never commit or print a populated DSN. No DSN-file loader or new
secret mount is introduced. The DSN is visible to Docker administrators through
container configuration; protect host access accordingly.

Use a dedicated PostgreSQL login with CONNECT on the Infra Sync database, USAGE
on the application schema, SELECT(key,value) on schema_meta, and column-level
SELECT on sources for the 15 projection columns plus id (WEB-1 health currently
reads id in a LIMIT 0 projection). Grant no table-wide source SELECT if credential
reference access should be prevented at the database layer. Do not grant writes,
schema CREATE, role administration or migration ownership. An operator must
review/apply permissions separately; WEB-2 never creates roles or changes grants.

The API must have private network reachability to PostgreSQL. Docker's localhost
is the container itself. Use the operator-managed private network/address; do not
publish PostgreSQL to the Internet. A supplied DSN is shared by health and source
visibility. Existing unbaselined registry v1 works without migration.

The reported production binding is 127.0.0.1:8001 -> container:8000. The checked-in
Compose default remains 8000; use INFRA_SYNC_WEB_PORT=8001 for that deployment.
View it through an SSH tunnel, replacing the example user/host:

```sh
ssh -N -L 18001:127.0.0.1:8001 operator@infra-sync-server
```

Open http://127.0.0.1:18001 and select Sources. Locally, run the API and Vite as
above, supplying only a disposable registry connection if testing data access.
This remains unauthenticated: never expose it publicly. Source addresses and
target metadata are operationally sensitive even without credentials.

## WEB-2 tests

```sh
pytest -q tests/test_api_sources.py tests/test_api_sources_postgres.py
cd frontend
npm test
npm run typecheck
npm run build
```

Node's built-in test runner tests source response validation and client errors;
no frontend test framework dependency was added. PostgreSQL tests require
INFRA_SYNC_TEST_POSTGRES_DSN explicitly targeting database `infra_sync_test`.
They create a unique infra_sync_test_* schema, initialize fixture data only in
that disposable database, and drop that exact schema during cleanup. Never point
the test variable at production. Ordinary tests skip PostgreSQL when unset.

Recommended WEB-3: authentication/access-control foundation and broader UI/DB
integration coverage before adding write operations. Keep source CRUD, secret
writes, execution and scheduler cutover under separate explicit approval.
