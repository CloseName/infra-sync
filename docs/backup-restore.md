# Infra Sync backup and fresh restore

Status: Backup Format v1 is the supported operator workflow for the canonical
Debian Deployment Foundation. Bundled PostgreSQL 16 is the primary tested mode;
external PostgreSQL is an advanced mode that requires compatible PostgreSQL client
tools and an operator-provided maintenance DSN.

Backups contain credentials and are highly sensitive. Keep the local directory
root-only, encrypt a copy with an approved external tool such as `age`, GPG, or the
corporate backup system, and move that encrypted copy off the Infra Sync VM. Infra
Sync does not invent an encryption format and does not delete or retain old backups
automatically.

## Persistent-state inventory

The required state is:

- a logical custom-format dump of database `infra_sync`, including schema
  `infra_sync`, `schema_meta`, `sources`, `sync_runs`, `alembic_version`, indexes,
  constraints and every application schema object;
- `/opt/infra-sync/config`: the six canonical env files, preserved byte-for-byte,
  including unknown operator keys;
- `/opt/infra-sync/secrets/infrastructure`: the bootstrap and fixed runtime-role
  password files;
- `/opt/infra-sync/secrets/sources`: exact logical filenames and broker xattrs;
- `/opt/infra-sync/secrets/netbox`: separate read and apply token files when
  configured;
- a manifest identifying the active immutable release and deployment/database
  metadata.

The release itself is optional and is not bundled. Retain the immutable source/image
identified by the manifest. The bundle excludes `current`, `releases`, `state`, the
PostgreSQL physical volume, Unix sockets, the shared lock, PID/container metadata,
logs, checkout files, caches, `node_modules`, and image layers. No runtime item under
`/run` is required after reboot or restore.

NetBox remains an external system of record and is not copied by this workflow. Its
managed v1/v2 custom-field identities remain in NetBox; restoring the exact
`source_instance`, source type, target settings, credential references, and secret
filenames preserves the corresponding Infra Sync identity namespace without source
re-registration.

## Bundle Format v1

The default destination is `/opt/infra-sync/backups` (0700). A complete directory is
published atomically only after verification:

```text
infra-sync-backup-YYYYMMDD-HHMMSS/
  COMPLETE
  manifest.json
  checksums.sha256
  database.dump
  state.tar
```

Payload files are 0600. `database.dump` is produced by `pg_dump -Fc --no-owner
--no-acl`; it never contains cluster-level roles. `state.tar` is a GNU pax tar made
with numeric owners and the `user.infra_sync.*` xattr namespace. Broker-created
source secrets require `user.infra_sync.operation`, `user.infra_sync.receipt`, and
`user.infra_sync.complete`.

The manifest contains format/application/release versions, UTC time, Compose project,
PostgreSQL major, database/schema, Alembic revision, source/run/secret counts, exact
file metadata, config file names, and logical credential references. Broker xattr
values are fingerprinted because the rollback receipt is an authorization value; the
real values exist only in the protected tar. Passwords, tokens, DSNs, raw payloads,
and secret contents never enter the manifest or operator log.

Every payload plus the manifest has a SHA-256 entry. `COMPLETE` is written only after
the dump is listable with `pg_restore`, the tar is structurally safe, source file
references resolve, and all checksums pass. A failure removes only its hidden staging
directory and never touches a previous backup.

## Create, inspect, and verify

Run from the active release as root:

```sh
cd /opt/infra-sync/current
sudo python deploy/backup.py create
sudo python deploy/backup.py create --output /protected/backup-target
sudo python deploy/backup.py verify /opt/infra-sync/backups/infra-sync-backup-TIMESTAMP
sudo python deploy/backup.py inspect /opt/infra-sync/backups/infra-sync-backup-TIMESTAMP
sudo python deploy/backup.py list
```

`inspect` and `list` expose only timestamp, application/release, source/run counts,
PostgreSQL major, Alembic revision, total size, and checksum status. There is no delete
command.

Exit status is `0` only on success. Failures use a stable safe class such as
`BACKUP_FAILED`, `BACKUP_LOCKED`, `BACKUP_INVALID`, `RESTORE_LOCKED`,
`RESTORE_INVALID`, `RESTORE_TARGET_NOT_EMPTY`, or `RESTORE_INCOMPATIBLE`; raw database
or secret-bearing exceptions are not printed.

Create records whether the timer was active, stops it, waits boundedly for
`/run/infra-sync/apply.lock`, and never kills an active apply. Once it owns that same
inode, it stops API, broker, discovery, apply, and schedule-control services.
PostgreSQL remains online. This short maintenance window prevents onboarding,
schedule, run-history, secret, scheduled, and manual-apply writes while the database
and filesystem snapshots are taken. It restarts exactly the previously running
services and restores the prior timer state on success or backup failure. A restart
failure makes the command fail even if a completed bundle remains useful.

For external PostgreSQL, install compatible client tools and provide the protected
value without putting it in argv or source control:

```sh
sudo --preserve-env=INFRA_SYNC_BACKUP_DSN \
  python deploy/backup.py --postgres-mode external create
```

The maintenance DSN must dump all Infra Sync objects. Restore also requires permission
to replace them and `SET ROLE infra_sync_owner`; do not reuse a runtime reader. The
value is inherited only by the operator process/client tools and is never printed.

## Supported fresh restore

The supported target is a clean Debian host with the Foundation installed, its
intended immutable release active, PostgreSQL reachable, fixed roles bootstrapped,
and no source/history rows. First perform a no-write check:

```sh
cd /opt/infra-sync/current
sudo python deploy/backup.py restore /protected/infra-sync-backup-TIMESTAMP --check
sudo python deploy/backup.py restore /protected/infra-sync-backup-TIMESTAMP
```

Restore verifies format, checksums, archive paths/types, xattr contract, dump
readability, PostgreSQL direction, Alembic compatibility, canonical layout, and empty
`sources`/`sync_runs` before the first write. The empty check is repeated inside the
maintenance lock after all writer services stop; two datasets are never merged.

The write sequence is:

1. stop the timer, acquire the shared lock, and stop writer/control services;
2. extract config/secrets into root-only staging and validate exact paths, uid/gid,
   mode, and xattr fingerprints;
3. replace only Foundation schema objects with `pg_restore --clean --if-exists
   --no-owner --no-acl --role=infra_sync_owner`;
4. run the tracked Alembic tool forward to target head and reapply tracked grants;
5. create a transient root-only password view containing the target bootstrap password
   and restored runtime passwords; the tracked `restore-role-passwords` operation
   rotates runtime roles first and bootstrap last;
6. preserve the clean target's allowlisted host-local Compose project, image, bind
   port, volume, lock, and canonical path values; then atomically replace `config`
   and `secrets`, preserving portable operator keys, logical source refs,
   infrastructure passwords, NetBox token separation, owners, modes, and xattrs;
7. compare source/run counts, credential references, and Alembic head;
8. start ordinary API/control workers and require API health plus Diagnostics.

The scheduler timer remains stopped. Run Diagnostics, Run Discovery, and Build Plan
for each source. Confirm identity resolution and expected `NO_CHANGE` or
`REVIEW_REQUIRED`, then explicitly enable the timer. Restore never invokes apply.

Filesystem publication uses staging and per-directory atomic renames. Database plus
filesystem restore cannot be one transaction. If a restore stage fails, timer and
writers remain stopped, success is not reported, and the fresh target is considered
dirty: diagnose or recreate it before retrying. There is no automatic DB rollback.

## Compatibility and limitations

- Backup Format v1 is accepted by this v1 tool. Unknown future formats are rejected.
- The backup Alembic revision must be in the target tool's reviewed chain. The same
  revision restores directly; an older known revision migrates forward. A newer or
  unknown revision is rejected before writes. Downgrade is never attempted.
- Logical restore from PostgreSQL 16 to 16 or a newer server major is allowed for
  rehearsal; an older target is rejected. Client/server tools must be compatible.
  Physical volume copying is unsupported.
- Fresh restore is supported. Replacing a populated/unknown installation is not.
  There is intentionally no `--replace-existing`; use a fresh VM or a separately
  reviewed disaster runbook and pre-restore backup.
- Fresh restore reproduces portable operator config and unknown keys. It deliberately
  retains the clean target Foundation's Compose project, application image, web port,
  PostgreSQL volume, apply-lock directory, and canonical config/secret paths. Review
  external-DB or future host-local values while the timer is stopped. Backup and
  application upgrade remain separate operations.
- xattrs are mandatory for broker-created source secrets. A filesystem without
  working `user.*` xattrs is unsupported and fails closed.

## Recovery rehearsal checklist

Backup:

1. confirm health and protected free space;
2. create the bundle;
3. run `verify` and `inspect`;
4. encrypt and copy it off-host; retain the immutable release from the manifest.

Restore:

1. build a clean Foundation at the same or reviewed newer release;
2. run `restore ... --check`, then `restore`;
3. confirm Health, Diagnostics, Sources, and Run History;
4. run read-only Discovery and Build Plan for Proxmox and ESXi;
5. verify permissions/xattrs and expected identity/no-change behavior;
6. enable the timer explicitly and observe one scheduled tick;
7. reboot and repeat health/history/source checks.

For upgrades, the future handoff is: verified backup, prepare immutable new release,
forward migration, then activation. The installer does not silently combine backup,
restore, and upgrade.
