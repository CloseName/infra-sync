# Frontend foundation (UI-0 / UI-1)

The React application uses React Router in declarative BrowserRouter mode.
Routes: Overview `/`, Sources `/sources`, registration `/sources/add`,
source `/sources/:sourceInstance`, Runs `/runs`, run `/runs/:runId`,
and Diagnostics `/diagnostics`. Add Source is an action within Sources.
Settings is intentionally absent. Source detail, Runs, Diagnostics and registration
retain their existing workflows; their full redesign is deferred.

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
