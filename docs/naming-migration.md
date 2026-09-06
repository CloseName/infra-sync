# NetBox Sync naming transition

This is an explicit maintenance operation for an existing Infra Sync Foundation.
Do not run it while either scheduled or manual apply can start. It preserves source
identities, registry rows, run history and logical source-secret filenames.

## Preconditions and first rollback boundary

1. Take and verify an old-format supported backup.
2. Stop and disable `infra-netbox-sync.timer`; stop the API and all control/writer
   services without killing an active apply.
3. Acquire the old `/run/infra-sync/apply.lock` and retain it through cutover.
4. Require `/opt/infra-sync` to be canonical and `/opt/netbox-sync` to be absent.
   Coexistence is a conflict, not a merge instruction.
5. Run the environment preflight; it reports key counts only and never values:

   ```console
   sudo python deploy/migrate_naming.py --root /opt/infra-sync
   ```

   Unknown `INFRA_SYNC_*` keys, duplicate keys, or different old/new values stop
   the transition. Unknown non-product operator keys are retained byte-for-byte.
6. Confirm that only `infra_sync` database/schema/roles exist and that Alembic is
   at `0001_registry_baseline` or `0002_sync_run_history`. The target names must
   not already exist.

Before the database rename, rollback is simply restarting the old units and timer.

## Staged transition

1. Copy `/opt/infra-sync` to `/opt/netbox-sync` with ownership, modes and xattrs
   preserved. Do not remove or alter the old tree.
2. In the staged copy, translate the reviewed environment keys:

   ```console
   sudo python deploy/migrate_naming.py --root /opt/netbox-sync --apply \
     --confirm MIGRATE_INFRA_SYNC_ENV_TO_NETBOX_SYNC
   ```

3. Using the new release image and protected bootstrap credential, run the
   operator-only `netbox_sync.deployment migrate-naming` command with
   `NETBOX_SYNC_NAMING_CONFIRM=RENAME_INFRA_SYNC_DATABASE_TO_NETBOX_SYNC`.
   It preflights the complete DB/schema/role namespace before its first write,
   rejects active DB sessions and conflicts, creates the fixed target roles, then
   renames the database/schema and transfers only allowlisted Foundation ownership.
   Legacy roles remain available through the verification/rollback window; no role,
   table, schema or row is dropped or recreated. Target passwords come from the
   same protected files and are loaded before the first database mutation.
4. Run Alembic to `0003_netbox_sync_naming`, then apply the complete target grant
   matrix. Verify source/run counts, identities and every runtime role.
5. Install `netbox-sync.service` and `netbox-sync.timer`, keeping the timer disabled.
   Verify both scheduled and manual paths use `/run/netbox-sync/apply.lock`.
6. Start the target runtime and perform read-only health, diagnostics, sources and
   history checks. Only then release the old lock.

The old systemd units, `/opt/infra-sync`, `/run/infra-sync` and old backup bundles
are not removed by project tooling. Retire them only in a separately approved host
cleanup after reboot and rollback-window validation.

## Second rollback boundary

After DB/schema/role rename, do not run the old runtime against the renamed DB.
Rollback uses the verified pre-transition backup on a fresh old-name Foundation,
then reinstalls the old tracked units. Never attempt an in-place reverse migration,
database merge, `DROP ... CASCADE`, or partial role recreation.

## Backup and xattr compatibility

New bundles use the `netbox-sync-backup-*` prefix and `user.netbox_sync.*` broker
xattrs. Restore continues to recognize verified format-v1 bundles with the old
product/schema and `user.infra_sync.*` receipt set. The broker reads either one
complete receipt set, rejects partial or conflicting dual sets, and writes only the
new namespace. Per-source logical filenames and registry references never change.
