# WEB-1: read-only System Health

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

Recommended WEB-2: read-only source summaries through allowlisted DTOs and an
application service, with credential redaction and access-control design before
introducing mutations. Do not change scheduling or add execution endpoints as
an incidental extension of the health page.
