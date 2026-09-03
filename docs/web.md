# WEB-2: read-only System Health and Sources

The optional Web/API shell does not execute discovery, plans or sync. Existing
CLI, registry-all behavior, identities, confirmations, systemd and locks are
unchanged. No production cutover or migration is part of WEB-1.

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
