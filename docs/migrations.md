# PostgreSQL migration procedure

WEB-0 introduces Alembic, isolated from synchronization. Never run this procedure
against production without an approved backup and restored-copy rehearsal.
No migration has been run against production by this change.

## Tooling and execution

The canonical deployment runs the migration from the packaged application image; host
Python and a host virtual environment are not required:

```sh
docker compose --env-file /opt/infra-sync/config/compose.env \
  -f /opt/infra-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps infra-sync-migrate
```

For development only, `python -m pip install -r requirements-migrations.txt` followed by
`alembic -c alembic.ini upgrade head` remains supported. In that mode supply
`INFRA_SYNC_REGISTRY_DSN` and `INFRA_SYNC_REGISTRY_SCHEMA` through the operator's
protected environment. The canonical one-shot instead reads its owner password from
the protected infrastructure-secret directory and builds the connection internally.
Do not put either credential in alembic.ini, command arguments, logs or source control.
Do not use `stamp` to bypass validation. Offline SQL generation is rejected because
existing-table validation requires a live PostgreSQL connection.

## Baseline behavior

- Clean schema: create sources and schema_meta using a frozen v1 definition.
- Existing v1: validate exact columns, types, nullability, defaults, primary keys,
  source_instance uniqueness, safety checks and schema_version. Do not rewrite
  source rows, timestamps, identities, flags, references or settings.
- Partial/unknown/drifted schema: fail and roll back. Investigate on a copy; do not
  "repair" production by deleting tables or manually stamping a revision.
- Alembic version table lives in the selected registry schema, not public.
- A transaction-scoped PostgreSQL advisory lock serializes these migration
  processes. DDL and the revision marker commit together. Lock waits are bounded.
  Legacy initialize() does not take this lock: keep administrative DDL/bootstrap
  stopped during migration. Runtime never invokes migrations automatically.
- Repeating upgrade head does nothing after success. Downgrade is deliberately
  rejected. Use additive, reviewed forward fixes; do not autogenerate drops.
- Revision `0002_sync_run_history` adds only `sync_runs`, its constraints and
  indexes. It does not update `sources`, `schema_meta`, identity metadata or the
  legacy registry version (`schema_version=1`). An existing exact v1 registry is
  first validated/stamped by the baseline in the same migration transaction,
  then receives the additive history table. A partial, drifted or newer legacy
  schema still fails closed before WEB-6 DDL is committed.
- Current SourceRegistry.initialize() remains unchanged for compatibility. Once
  migrated, operators use Alembic for schema evolution rather than extending
  initialize(). Future revisions must remain independent of mutable runtime code.

The migration owner is provisioned separately from runtime roles. The tracked
`infra-sync-db-grants` operation reapplies the exact least-privilege matrix after
migration; see [Deployment](deployment.md#database-lifecycle-and-roles).

## Validation

Unit tests validate revision discovery, offline rejection, frozen schema and drift
checks without a server. Opt-in integration tests exercise a clean install,
populated legacy adoption, repeated upgrade, unknown version and rollback. Set
`INFRA_SYNC_TEST_POSTGRES_DSN` only to a disposable database named `infra_sync_test`.
Tests create unique schemas and remove only their own schemas on cleanup. Never
point this variable at a production database. PostgreSQL tests may skip when the
test DSN is absent; such a pass is not evidence of a live migration rehearsal.

WEB-6 adds opt-in round-trip coverage for RUNNING/terminal lifecycle, duration,
counts, snapshots, newest-first listing and filters. The migration owner remains
separate from the runtime run-writer role. Exact runtime grants and the production
rollout checklist are documented in [Web deployment](web.md#web-6-durable-run-history).

The connection-sharing/transaction approach follows the
[official Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).
