# Infra Sync architecture — WEB-0 foundation / WEB-1 read-only shell

Status: an opt-in API and frontend now provide read-only health reporting.
No worker daemon or new scheduler is enabled. Production runtime remains the
authority. See [WEB-1](web.md) for the implemented boundary and startup commands.

## Current state, verified from code

- `nbpxsync = netbox_pve_sync:main` is the installed entrypoint.
- `source_bootstrap` selects legacy, registry or registry-all configuration.
  Registry-all reads `enabled AND sync_enabled`, ordered by source ID. It rejects
  multiple legacy identity owners. It does not enforce per-source intervals.
- `orchestrator.run_sources` executes sequentially, isolates exceptions and
  SystemExit per source, and reports aggregate success/failure. The CLI exits 1
  if any selected source fails. There is no durable queue or run history.
- `SourceExecutorDispatch` selects Proxmox or ESXi. Source secrets resolve at
  their connection boundaries; discovery produces shared domain objects.
- `execute_discovered_source` selects the NetBox read/write token at bootstrap.
  Proxmox full apply validates host, VM, VM network, LXC, LXC network and
  disappearance stages before writes. ESXi runtime builds a migration plan,
  filters MANAGED VMs, and prechecks VM plus VM network before either writes.
- ESXi REVIEW_REQUIRED, NEW, safe legacy and ambiguous candidates are not
  auto-adopted. ESXi host matching is reported; host networking is excluded.
  Controlled adoption/bootstrap helpers remain separate explicit operations.
- `SourceRegistry` uses psycopg, parameterized SQL, immutable SourceConfig,
  unique source_instance, reference-only credentials and optimistic updates.
  `initialize()` creates `schema_meta` and `sources`, with schema_version=1.
- `FileSecretResolver` supports env and logical file names beneath
  `/run/secrets/infra-sync`. LegacyFileSecretResolver supports old absolute
  paths. NetBox credentials still use the existing bootstrap environment/file
  reader. No new secret provider is activated.
- `scripts/run-full-sync.sh` uses flock, the shared lock path and Compose full
  apply with FULL_WRITE. The production systemd unit independently acquires the
  same lock before invoking the operator-managed registry-all wrapper at
  `/opt/infra-sync/run-full-sync-registry.sh` every 10 minutes.
- Compose currently builds one CLI image, mounts secrets, and joins external
  `netbox_default`. It does NOT declare PostgreSQL or registry-all environment.
  The reported live registry-all setup therefore includes operator configuration
  beyond these checked-in files; WEB-0 does not inspect or overwrite that setup.
- Tests use fake NetBox/Proxmox/ESXi, plus opt-in live/isolated PostgreSQL tests.
  `.forgejo/workflows/ci.yaml` runs pytest and pylint >=9.0; these workflows are
  not GitHub Actions. CD still describes upstream-style PyPI publication.

## Lowest-risk layout

```text
netbox_pve_sync/                 existing runtime, domain, adapters: unchanged
  application/                  new, opt-in transport-neutral contracts
docs/                           architecture, migration and development guides
migrations/                     Alembic environment and immutable revisions
deploy/systemd/                 existing production scheduler: unchanged
scripts/                        existing production wrapper: unchanged
tests/                          old suite plus foundation coverage
compose.yml + compose.apply.yml existing production entry: unchanged
alembic.ini                     migration paths, never credentials
requirements-migrations.txt     operator tooling, not runtime dependencies
```

WEB-1 adds `netbox_pve_sync/api/` (FastAPI) and `frontend/` (React/TypeScript,
Vite). No top-level backend package is needed: API, application and worker code
can share the existing distributable Python package. Do not move stable modules
for cosmetic layering. Migration dependencies are dev/operator-only for now;
the current Dockerfile and base distribution dependencies remain unchanged.
Web dependencies are an optional extra. Dockerfile.web builds that extra plus
frontend assets; Compose adds an opt-in API role in the same project. This avoids
changing the deployed CLI image before an approved cutover.

## Component contracts

| Layer | Owns | Must not do |
|---|---|---|
| API (future) | request validation, response DTOs, access-control seam | run shell commands, expose raw registry records/secrets, reimplement reconciliation |
| Application | use-case policy, run context, confirmation and safe result contracts | depend on HTTP or mutate process environment per request |
| Worker | durable claim, invoke existing executor, record result | bypass prechecks, grant itself confirmation, run overlapping applies |
| Sync/domain | discovery, identities, planners and guarded appliers | depend on API/frontend |
| Registry/data access | source configuration and concurrency rules | hold plaintext credentials |
| PostgreSQL | registry now; jobs/history later in additive tables | become a second copy of NetBox inventory |
| Frontend | views of safe API DTOs and explicit operator intent | connect directly to PostgreSQL/NetBox/source APIs |
| SecretReader | resolve a SecretReference only at execution | serialize the resolved value |
| Scheduler | submit due work through the same application port | perform reconciliation or run beside an independent competing scheduler |

The new contracts do not hook into the existing CLI. `SecretReader` structurally
matches FileSecretResolver. `PreflightSubmitter` is deliberately read-only intent;
there is no implemented queue and no generic `confirmed=True` web command.

## Future request/run flow

```text
API request or scheduler tick
  -> application service: validate source + create RunContext
  -> PostgreSQL job transaction (future)
  -> worker claims job with same run_id
  -> existing SourceExecutorDispatch -> adapter -> discovery -> guarded runtime
  -> allowlisted result/events -> PostgreSQL history -> API DTO -> frontend
```

Allocate a UUID once per source execution. Persist/transport its canonical string;
rehydrate the same UUID in the worker. Never create a new ID at each layer. A
multi-source request will have a separate batch/request ID and one run_id per
source. Worker delivery retry reuses that ID; a new operator-triggered run gets a
new ID. A repeated apply is not authorized merely because its run_id matches.
Future crash recovery must distinguish unknown/partial apply from safe retry.

Legacy CLI consumes environment variables and prints text. WEB-1 must introduce
an injectable bootstrap adapter before concurrent request execution; do not set
os.environ per HTTP request and do not parse stdout into an API contract.
Initially use a single execution lane preserving the existing global lock.

## Safety and authorization boundaries

No deletes; stable v2 identities and existing Proxmox legacy ownership; no
name/fuzzy auto-adoption; no automatic VLAN/Prefix creation; no foreign IP/MAC
stealing; preserve manual fields and same-VM manual primary; retain disappearance;
global prechecks before writes; explicit confirmation; idempotency; REVIEW_REQUIRED
report-only; no silent legacy adoption of NEW objects. Preserve the current
difference: truly new Proxmox objects use existing guarded create policy, whereas
ESXi normal runtime reports NEW and uses separate confirmed bootstrap.

Global precheck means all stages within one source run, not an atomic distributed
transaction across sources or across all NetBox HTTP writes. A failure after the
first write can leave partial progress; future run history must report this.

Web apply needs explicit operation/scope and a server-side confirmation tied to
fresh plan, source and target. Authentication is deferred, not authorization or
confirmation checks. Reserve a request-principal dependency and middleware seam
for OIDC/LDAP/reverse-proxy auth. Until authentication exists, any API must bind to
loopback/private trusted access only; write APIs require a separate security review.

## Database ownership

Infra Sync owns its configured application schema, not NetBox's database. Keep
the current schema and rows in place. Alembic baseline validates legacy v1 before
recording its revision; clean installs create the same tables. No schema rename,
copy, drop or automatic startup migration. `schema_meta.schema_version=1` remains
the legacy registry contract; `alembic_version` tracks application migrations.
Future additive Web tables do not require bumping legacy schema_version.
See [migration procedure](migrations.md) for backup, locks and failure handling.

## Secrets

Preserve all current references and mounts. API DTOs must be explicit allowlists,
not serialization of SourceConfig/SourceRecord/settings. Never include credentials,
DSNs, environment dumps, connection exceptions or raw API payloads. File paths and
usernames may also be sensitive: only disclose intentionally safe status.

Future protected-secret writes require a separate write port: atomic file replace
or encrypted storage, restrictive permissions, reference validation, rotation and
audit. Encryption keys cannot live alongside ciphertext in the registry. No such
write path or secret migration is implemented in WEB-0. The API should not mount
source/NetBox write secrets; the worker receives only those it needs.

## Observability convention

One JSON object per event: timestamp (UTC ISO 8601), level, component,
source_instance, run_id, error_code (nullable), message. The new event builder
uses fixed enums/messages and takes no arbitrary exception or payload. Only a
validated operator source identifier may populate source_instance; it must never
be populated from a credential. No root-logger reconfiguration or changes to
current stdout occur. This is not a universal sanitizer of existing runtime logs.

Stable codes are defined in `application/observability.py`: SOURCE_AUTH_FAILED,
SOURCE_UNREACHABLE, SOURCE_TLS_FAILED, SOURCE_CONFIG_INVALID, SOURCE_SECRET_MISSING,
NETBOX_AUTH_FAILED, NETBOX_UNREACHABLE, NETBOX_TARGET_INVALID, REGISTRY_UNAVAILABLE,
RUN_PRECHECK_FAILED, RUN_APPLY_FAILED, RUN_INTERNAL_FAILED. Keep their meaning
stable; messages can evolve. Map typed failures at adapter boundaries in a later
phase; never guess auth/TLS failure from arbitrary exception text. Unknown failures
use RUN_INTERNAL_FAILED with a generic message. Raw runtime logs are not API-ready.

## Compose and deployment transition

Target: one repository, one Compose project, one application image used by API,
worker and a one-shot migration role; PostgreSQL with a persistent named volume;
frontend build assets served by API initially (separate web container only if
justified). No Redis: PostgreSQL job claims/leases are sufficient until measured
otherwise. DB remains private with no host port by default. External NetBox stays
an integration, not part of our schema or ownership.

Future `docker compose up -d` must gate API/worker startup on DB health and a
successful explicit migration role, have least-privilege DB users, read-only
application filesystems, protected secret mounts and health/readiness endpoints.
This is a deployment contract, not a runnable Web stack in WEB-0. Existing
`infra-netbox-sync`, container_name, systemd filenames, references and lock paths
stay unchanged. Never run both systemd and a new worker scheduler against the
same sources without a shared exclusion strategy. Cutover requires explicit
operator approval, rollback plan and a tested database backup/restore procedure.

## Deferred and approval gates

WEB-1: minimal FastAPI health/read-only source DTOs and application adapter,
React/TypeScript shell, development Compose roles and integration tests. No
Sync Now/write controls until confirmation and lock/lease behavior are tested.
Then add durable jobs/history, source scheduling, protected secrets and the
remaining Web v1 workflows incrementally. Auth integration comes later.

Before production cutover: test migration on a restored copy, reconcile actual
server Compose/registry configuration, review unauthenticated exposure, and approve
scheduler ownership. Portable full application startup is a target, not delivered
yet. Python metadata still advertises >=3.8 despite syntax requiring >=3.10;
Docker uses 3.12 and existing CI 3.13. Dependency manifests also differ (pyVmomi is
in pyproject but not requirements.txt). GitHub CI/publication and supported-version
alignment are separate follow-up changes, not silently bundled into WEB-0.
