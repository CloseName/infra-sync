# PostgreSQL migration procedure

WEB-0 introduces Alembic, isolated from synchronization. Never run this procedure
against production without an approved backup and restored-copy rehearsal.
No migration has been run against production by this change.

## Tooling and execution

From the repository root in a dedicated operator environment:

```sh
python -m pip install -r requirements-migrations.txt
alembic -c alembic.ini history
alembic -c alembic.ini upgrade head
```

Supply `INFRA_SYNC_REGISTRY_DSN` and `INFRA_SYNC_REGISTRY_SCHEMA` through the
operator's protected environment. The DSN supports the same libpq connection
string/URI as the current runtime. Do not put it in alembic.ini, command arguments,
logs or source control. No default schema/DB is inferred. Do not use `stamp` to
bypass validation. Offline SQL generation is rejected because existing-table
validation requires a live PostgreSQL connection.

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
- Current SourceRegistry.initialize() remains unchanged for compatibility. Once
  migrated, operators use Alembic for schema evolution rather than extending
  initialize(). Future revisions must remain independent of mutable runtime code.

The migration role needs schema DDL permission; the future API/worker role should
have only required DML permission. Permissions and production rollout are operator
tasks, not performed by this repository change.

## Validation

Unit tests validate revision discovery, offline rejection, frozen schema and drift
checks without a server. Opt-in integration tests exercise a clean install,
populated legacy adoption, repeated upgrade, unknown version and rollback. Set
`INFRA_SYNC_TEST_POSTGRES_DSN` only to a disposable database named `infra_sync_test`.
Tests create unique schemas and remove only their own schemas on cleanup. Never
point this variable at a production database. PostgreSQL tests may skip when the
test DSN is absent; such a pass is not evidence of a live migration rehearsal.

The connection-sharing/transaction approach follows the
[official Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).
