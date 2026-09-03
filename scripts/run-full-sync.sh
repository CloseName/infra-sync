#!/bin/sh
set -eu

cd /opt/infra-sync/src

exec /usr/bin/flock \
  -n \
  /run/infra-netbox-sync.lock \
  /usr/bin/docker compose \
    -f compose.yml \
    -f compose.apply.yml \
    run \
    --rm \
    --no-deps \
    -v /opt/infra-sync/src/netbox_pve_sync:/app/netbox_pve_sync:ro \
    -e PYTHONPATH=/app \
    -e SYNC_MODE=apply \
    -e APPLY_SCOPE=full \
    -e APPLY_CONFIRM=FULL_WRITE \
    infra-netbox-sync
