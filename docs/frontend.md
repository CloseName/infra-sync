# Frontend foundation (UI-0 / UI-1 / UI-2)

The React application uses React Router in declarative BrowserRouter mode.
Routes: Overview `/`, Sources `/sources`, registration `/sources/add`,
source `/sources/:sourceInstance`, Runs `/runs`, run `/runs/:runId`,
and Diagnostics `/diagnostics`. Add Source is an action within Sources.
Settings is intentionally absent. Source detail and scheduling are organized into
source sections below. Global Runs, Diagnostics and registration retain their existing workflows.

FastAPI serves the same built index only for the explicit frontend paths.
Unknown API routes, missing assets and unknown frontend paths do not fall back
to HTML. Vite provides the local development fallback. No API DTO or privilege
changes were made.

Overview independently reads sources, diagnostics, and the latest 50 runs.
It shows eight recent runs, up to five source attention items, up to three stale
record links, and five next-expected schedules. Running counts cover only the
returned recent records. Stale counts cover only the returned diagnostics
selection (currently limited to 100); neither is a global live total.
Provider connectivity, persisted snapshots, changes-waiting and applied-in-24h
metrics are not inferred. Expected schedule timestamps are not guaranteed starts.

Sources joins the full configuration list to diagnostics by exact source_instance.
Diagnostic projections are used only when registry and history checks are healthy.
Unavailable diagnostics never remove configuration rows or imply healthy status.
Source enabled, automatic sync, recorded outcome, and attention remain distinct.
Attention is derived in priority order: uncertain/partial, unhealthy/unavailable,
stale, delayed, failed/blocked/locked outcome, other reported warnings.

Sources search, provider/health/schedule/attention/site filters, sort/direction,
page and 25/50/100 page size live in URL query parameters. Filtering and pagination
apply to the complete returned source list, not to a partial run selection.
Source links preserve the originating query in browser history state.
Client-side operation is verified with 105 unit-test rows and 55 browser-fixture
rows. At several hundred sources, measure payload, join/render time and diagnostics
query latency before increasing scale. Server-side filtering/pagination and explicit
coverage metadata are follow-up backend work, not claimed by this UI.

Resources retain successful data on failed refresh and display its received time.
Requests have a 15-second client timeout, unmount cancellation, and no automatic
refresh or write retry. An aborted HTTP request does not promise server cancellation.
Source components are remounted by route identity to isolate in-flight local results.

Shared UI files under src/ui own health/schedule/outcome labels, attention/query
derivations, human date/duration formatting, primitives and light-theme tokens.
Unknown is neutral. Technical enums remain available as titles or aggregate text.
The token layer permits future themes; no theme switcher or stored preferences
are introduced.

Validation:
- `npm test`: existing API client tests and deterministic projection tests.
- `npm run typecheck`, `npm run build`.
- `npx playwright install chromium`, then `npm run test:e2e`.
- Browser tests intercept every API call; only local Vite is started, with no
  provider, NetBox, registry, or production connection. Screenshots go to ignored
  test-results at 1440/1280/1024/768 widths.
- `python -m pytest tests/test_frontend_routes.py tests/test_api_health.py`.
- Build Dockerfile.web with a local Docker daemon before release.

The shell includes a skip link, route breadcrumbs, active navigation, route focus,
native controls, labeled filters, sortable table headers, controlled table overflow,
and reduced-motion rules. Browser checks cover navigation, direct refresh, basic
keyboard access and overflow; they are not a WCAG conformance certification.

## Source Detail and Schedule (UI-2)

Pre-implementation baseline: `e5f797020837e98c8eabdb4249245a504dbdd10c`
(the full tested UI-0/UI-1 baseline is recorded in git history). The old detail page
combined configuration, raw-second scheduling, Discovery and Plan/Sync in one
vertical view. Runs already supported a source_instance filter, and diagnostics
already projected per-source activity. No new API data contract was needed.

Source sections are addressable links:

| Section | Route | Content |
| --- | --- | --- |
| Overview | `/sources/:sourceInstance` | Activity, schedule, target and attention |
| Sync | `/sources/:sourceInstance/sync` | Existing read-only Discovery, exact Plan and manual result |
| Runs | `/sources/:sourceInstance/runs` | Latest 50 records filtered by exact source_instance |
| Schedule | `/sources/:sourceInstance/schedule` | Schedule evidence and human-readable editing |
| Diagnostics | `/sources/:sourceInstance/diagnostics` | Source-only status, warnings, activity and evidence time |
| Configuration | `/sources/:sourceInstance/configuration` | Read-only identity, connection, target, provider mapping and TLS |

The source route wrapper is keyed by sourceInstance, while all section links use
one shared source component. Source configuration, schedule and diagnostics are
loaded once per source entry, not on each tab click. Source breadcrumbs and the
document title use the loaded display name. Unknown sources and temporary API
failures have separate states; retry preserves the URL.

Sync and Schedule remain mounted but hidden outside their sections, preserving
local results and edits across sibling tabs. Leaving the source discards that local
state. Read requests ignore late responses after unmount; schedule writes also
check component lifetime before publishing results. They cannot update a newly
mounted source, including a later visit to the same ID. HTTP cancellation does
not cancel work already accepted by the backend. No automatic write retry occurs.

Discovery is optional and makes no NetBox changes. Build Plan remains independently
available. Exact digest confirmation, the existing window.confirm prompt, shared
apply lock and stale-plan protection are unchanged. UI-3 will redesign the plan
review and confirmation experience. This phase does not imply new workflow gates.

The header separates source enabled, automatic sync, last run, last success and
attention. Registry enabled is configuration, not provider health. Diagnostic
status is evidence from persisted records, not a connectivity or authentication
check. UNKNOWN is shown as Not verified; unavailable evidence never implies
success. Schedule and diagnostics can have different observation times; Diagnostics
labels its scheduler value as being at evidence time. Running outcomes say
Recorded as running. Source-level stale warnings do not prove that a particular
latest run is stale. Diagnostic warnings remain visible separately.

Source Runs requests `/api/v1/runs?source_instance=...&limit=50`, rejects foreign
source rows, and links to existing global run details. It is an explicitly bounded
recent list, not all-time history. Action counts describe the recorded plan, not
confirmed applied objects. Source Diagnostics links to system diagnostics instead
of copying global components. Configuration never exposes credentials and keeps
legacy ownership and stable identity in its advanced section.

### Human-readable schedules

Read mode shows On/Off, exact human frequency, recorded scheduled outcome/time,
derived scheduler state and next expected time. Expected is not guaranteed; the
API does not provide a live scheduler heartbeat.

Presets: 5, 10, 15, 30 minutes; 1, 2, 6 hours. Other stored values open as Custom,
with Seconds / Minutes / Hours. Existing values use the largest unit that preserves
an integer; 601 seconds remains 601 Seconds, and 9000 seconds displays 2 h 30 min.
Changing a unit or preset is an explicit user action. Decimal input is converted
using integer arithmetic and must produce exact whole seconds; 1.15 minutes is
69 seconds. No rounding or silent normalization occurs.

The existing contracts intentionally remain unchanged:
- Registration accepts 1..2147483647 seconds.
- Schedule updates accept 60..86400 seconds.
- Optimistic expected_sync_interval_seconds accepts the wider existing range.

Out-of-update-range values remain visible and unchanged. Editing explains the
mismatch and blocks saving until the operator explicitly chooses a supported
value. Even an enable/disable-only update must satisfy the current interval update
contract. Harmonizing registration/update validation is a documented backend
follow-up, not part of UI-2.

The editor distinguishes idle, editing, saving, saved, conflict and error. It
disables duplicate submissions, preserves inputs on failure, and sends the exact
loaded expected_sync_enabled and expected_sync_interval_seconds. A conflict
requires explicit reload; a failed reload keeps saving blocked. Reload awaits the
new response before updating the baseline. Save/read requests have a 15-second
client timeout. A transport failure may leave the server outcome unknown; there
is no automatic retry.

Enabling explains eligibility on a future scheduler cycle. Disabling explicitly
does not cancel a run that already started. A disabled source cannot run
automatically even when automatic sync is configured on.

### UI-2 validation

- 39 frontend unit tests, including exhaustive round-trip checks for every
  supported integer-second interval, plus custom units and legacy values.
- 42 Playwright tests in total: source direct routes/refresh, Back/Forward,
  keyboard links/forms, no redundant source reload between tabs, errors/conflict,
  late source/Discovery/Plan/Schedule responses and existing confirmation behavior.
- Screenshots inspected for Overview, Sync, Runs, Schedule read/edit, Configuration,
  warnings, schedule off, unusual intervals, invalid source and narrow layouts.
  Whole-page overflow checked at 1440, 1280, 1024 and 768 pixels.
- Strict TypeScript and Vite production build pass.
- 87 focused backend tests pass: frontend routes, API health/sources, scheduler
  and schedule worker. Only explicit read-only SPA entry routes changed in Python;
  no write contract, worker policy, DB migration or privilege boundary changed.
- Docker Engine 29.7.2 / Compose 5.5.0: Dockerfile.web builds successfully.
  Default Uvicorn, UID 10001, /app/web, read-only filesystem, network none, no
  mounts, credentials or published ports. Inside-container HTTP checks passed for
  /, /sources, /sources/add, /sources/test-source, all five source subroutes,
  /runs, /runs/test-run-id and /diagnostics.
- Unknown frontend/source paths, /api/unknown, /api/v1/unknown,
  /api/v1/sources/test-source/unknown and missing JS/CSS remain JSON 404.
  Served index and JS/CSS bytes match files inside the built image.
  The uniquely labeled smoke container and image were removed; no shared prune.
- git diff --check and changed frontend/documentation branding scan pass.

Browser writes use mocked APIs only. No live provider, NetBox, registry or server
was modified; no push or deploy. Deep Plan/Sync review, global Runs/Diagnostics,
onboarding and final visual polish remain deferred to UI-3 and later phases.
