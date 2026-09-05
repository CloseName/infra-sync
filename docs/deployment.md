# Canonical v1 deployment foundation

This is the supported clean-install foundation. It is code-ready but does not
authorize a production cutover. Rehearse it on a disposable Debian host and a
restored database before changing an existing installation.

## Topology

`compose.production.yml` defines one stable Compose project (`infra-sync`), one
application image and separate API, discovery, apply, schedule, secret-broker and
transient scheduler processes. Bundled PostgreSQL 16 is the default. Its deterministic
volume is `infra-sync-postgres-data`, it is attached to the private `infra-sync-db`
network and it has no host-published port. The API also joins a dedicated Web bridge
for its loopback-published port. Discovery, apply and scheduled execution
also join `infra-sync-egress` for normal HTTPS connections to providers and NetBox.
There is no NetBox Docker-network dependency. The broker is networkless and the
schedule worker has DB access only.

The runtime boundaries remain separate. In particular, the API has no source-secret
or NetBox-token mount and no schedule/run writer DSN. Migration/owner and bootstrap
credentials are mounted only read-only into explicit root one-shot tool containers.
The transient scheduler also runs as root with all capabilities dropped so it can read
root-owned 0600 source/NetBox files; it receives no host-control socket. All persistent
source credentials use the shared broker directory; onboarding a source requires no
Compose edit.

## Host layout

```text
/opt/infra-sync/
  releases/<release-id>/       immutable packaged release
  current -> releases/<id>     atomic active-release link
  config/                      generated service-specific env files (0750/0600)
  secrets/infrastructure/      generated database passwords (0700/0600)
  secrets/sources/             broker-managed source secrets (0700/0600)
  secrets/netbox/              read-token and apply-token files (0700/0600)
  backups/                     protected hook for the next Backup/Restore stage
  state/                       future persistent operator state
/run/infra-sync/               shared apply lock (0750)
```

Release directories and code are normalized to 0755 directories, 0644 data/code and
0755 executables. Secret creation uses exclusive `O_CREAT|O_EXCL`, explicit 0600 and
`fsync`; it never changes process-global umask. The installer never overwrites an
existing password. Do not copy secrets into a release directory.

## Fresh Debian foundation

Prerequisites are Python 3.10+, Docker Engine with Compose v2, systemd, `flock` and
`install`. The installer itself uses only the Python standard library; database and
migration code runs inside the application image.

From an unpacked reviewed release:

```sh
python3 deploy/install.py --check
sudo python3 deploy/install.py --release-id <release-id>
```

`--check` is read-only. `--prepare-only`, `--no-start`, and `--no-systemd` provide
bounded rehearsal/operator modes. The normal order is: create layout and credentials,
activate the release, start PostgreSQL, wait for readiness, bootstrap roles, migrate,
apply grants, start long-running services, install tracked units, then enable the timer.
Running the same release again reuses passwords and data and reruns only idempotent
provisioning steps; it does not delete sources or reset secrets.

The generated `compose.env` and service env files are Docker env files, **not shell
scripts**. Never use `source file` or `. file`; libpq values may contain spaces. Pass
them only with Compose `--env-file`/`env_file` as the tracked wrapper and installer do.

The zero-source state is valid: API/UI liveness does not require a source or live
NetBox, workers can wait for requests, and a scheduled registry-all tick evaluates
zero due sources without provider execution. NetBox URLs and token files are populated
later by the reviewed bootstrap/onboarding procedure; diagnostics may report them
unavailable meanwhile.

## Database lifecycle and roles

The one-shot services provide the supported host-venv-free operations:

```sh
docker compose --env-file /opt/infra-sync/config/compose.env \
  -f /opt/infra-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps infra-sync-db-roles
docker compose --env-file /opt/infra-sync/config/compose.env \
  -f /opt/infra-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps infra-sync-migrate
docker compose --env-file /opt/infra-sync/config/compose.env \
  -f /opt/infra-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps infra-sync-db-grants
```

Role bootstrap is fixed and idempotent. `infra_sync_owner` owns migrations;
`infra_sync_web_reader`, `infra_sync_discovery_reader`,
`infra_sync_apply_registry_reader`, and `infra_sync_registry_reader` are readers;
`infra_sync_registration_writer` can select and insert the exact source-registration
columns; `infra_sync_run_writer` can select/insert/update only run-history lifecycle
columns; `infra_sync_schedule_writer` can select/update only the two schedule columns.
Runtime roles receive no DELETE, TRUNCATE, DDL, role administration or writes to
`schema_meta`. PUBLIC schema/table/sequence and owner default table privileges are
revoked before the explicit grants are reapplied.

Migration remains explicit and never runs during API startup. Revision 0001 creates or
strictly validates the registry v1 baseline; 0002 only adds `sync_runs`. There is no
downgrade path. Always back up and rehearse a restored copy before production migration.

## Scheduled execution and locking

The tracked service calls `/opt/infra-sync/current/scripts/run-scheduled-sync.sh` every
60 seconds. That wrapper invokes the full canonical Compose file, so existing long-lived
containers belong to the same model and do not appear as orphans. It never uses
`--remove-orphans` and never bind-mounts source code.

The wrapper is the **only** scheduled `flock` owner. It locks
`/run/infra-sync/apply.lock`; the manual apply worker mounts only `/run/infra-sync` and
opens the same inode. A still-running oneshot cannot be started again by the timer, and
the shared lock remains the final barrier against manual/scheduled overlap.

## Optional external PostgreSQL

Bundled PostgreSQL is intentionally the default. For an operator-managed PostgreSQL,
combine `compose.production.yml` with `compose.external-postgres.yml`; the override puts
the bundled service behind an inactive profile and moves DB-only consumers/tools onto
the egress bridge so they can reach the operator endpoint. Supply service DSNs in the protected
generated env files and set `INFRA_SYNC_DB_HOST`/`INFRA_SYNC_DB_PORT` for one-shot tools.
The external server must provide the bootstrap database/user for initial role creation.
Do not expose or reuse NetBox's database.

## Existing-install transition and deferred work

Do not switch an existing deployment automatically. Back up the database/config/secrets,
rehearse the Alembic baseline, copy legacy source secrets into the broker directory,
populate generated service env files, build a pinned image, install the tracked unit,
then validate shared-lock contention before enabling manual or scheduled apply. The old
`compose.yml`, `compose.web.yml`, `compose.apply.yml`, and `scripts/run-full-sync.sh`
remain explicit compatibility artifacts only; they are not the clean-install path.

Full backup/restore, final naming, interactive onboarding, RBAC/LDAPS, TLS/reverse proxy,
resource limits, run-history retention and stale-run recovery are deliberately deferred.
The deterministic volume/layout and explicit migrations are the hooks for the next
Backup/Restore stage. Run history remains unlimited and stale RUNNING rows remain
diagnostic-only.
