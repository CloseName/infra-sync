#!/bin/sh
set -eu

install_root="${NETBOX_SYNC_ROOT:-/opt/netbox-sync}"
release_root="${install_root}/current"
config_root="${install_root}/config"

cd "${release_root}"
/usr/bin/install -d -m 0750 /run/netbox-sync

# This is the sole scheduled lock boundary. The manual apply worker mounts the
# same host directory and opens the same inode.
exec /usr/bin/flock -n /run/netbox-sync/apply.lock \
  /usr/bin/docker compose \
    --env-file "${config_root}/compose.env" \
    -f "${release_root}/compose.production.yml" \
    --profile scheduled \
    run --rm --no-deps netbox-sync-scheduler
