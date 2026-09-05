# Infra Sync

Synchronize infrastructure from multiple virtualization sources, including Proxmox VE and VMware ESXi, to NetBox.
This allows automatic tracking of Virtual Machines, disks, IP addresses/prefixes, MAC addresses, VLANs, ...

## How does it work?

Infra Sync discovers source inventory and reconciles it through guarded NetBox planning/apply paths.
Disappearance is retain-only; synchronization does not delete NetBox objects.

## Architecture and development

The current registry-backed runtime and the Web/API foundation are documented in
[Architecture](docs/architecture.md), [Development](docs/development.md), and
[Database migrations](docs/migrations.md). The opt-in [Web stack](docs/web.md)
includes durable manual/scheduled run history and read-only operator diagnostics; it does not
give the API systemd control. Per-source cadence is derived from scheduled run history;
systemd remains a fixed tick engine.
The standalone ESXi identity, compatibility, and safe multi-source validation contract
is documented in [Architecture](docs/architecture.md) and the
[operator runbook](docs/web.md#esxi-production-like-multi-source-validation-operator-runbook).
The Proxmox identity and legacy-compatibility contract is documented alongside the
[Proxmox production-like validation runbook](docs/web.md#proxmox-production-like-validation-operator-runbook).
The heterogeneous source isolation and readiness gate is documented in
[Architecture](docs/architecture.md#multi-source-system-contract) and the
[multi-source live checklist](docs/web.md#multi-source-live-validation-operator-runbook).
For a fresh host, use the [canonical v1 deployment foundation](docs/deployment.md).
The historical files and environment workflow below are retained only for compatibility.

## Canonical deployment foundation

Bundled private PostgreSQL, the API/workers/broker, explicit migrations, generated
role-separated configuration, and the tracked 60-second systemd scheduler are defined by
`compose.production.yml` and `deploy/install.py`. A clean installation does not join a
NetBox Docker network, does not bind-mount the source tree, and does not require static
per-source secret mounts.

```sh
python3 deploy/install.py --check
# After review on the target Debian host:
sudo python3 deploy/install.py --release-id <release-id>
```

See [Deployment](docs/deployment.md) before any rollout. The installer does not request
provider credentials and must not be aimed at an existing production host without a
backup and restored-copy rehearsal.

## Legacy package/environment compatibility

The package remains available as `netbox-pve-sync` and the legacy single-Proxmox mode is
kept for compatibility. It is not the canonical multi-source production deployment.

```sh
pip install netbox-pve-sync
```

### Configuration

### On NetBox

You'll need to create a dedicated user (ex: infra-sync) on your NetBox instance and then create a write API
token.

The following env variables will need to be set:

- **NB_API_URL**: The URL to your NetBox instance. (ex: https://netbox.example.org)
- **NB_API_TOKEN**: The token created previously. (ex: f74cb99cf552b7005fd1a616b53efba2ce0c9656)

You can also set the `NB_CLUSTER_ID` env variable in order to indicate the ID of the cluster that will be used in
NetBox.

You'll also need to perform a minimal configuration on NetBox:

- Create the physical nodes hosting the cluster. (The name should match the one on Proxmox, so that the script can
  correctly link the VMs to the physical host)
- Create the cluster.
- Add the following Custom Fields:

| Name       | Object types    | Label      | Type    |
|------------|-----------------|------------|---------|
| autostart  | Virtual Machine | Autostart  | Boolean |
| replicated | Virtual Machine | Replicated | Boolean |
| ha         | Virtual Machine | Failover   | Boolean |
| backup     | Virtual Disk    | Backup     | Boolean |
| dns_name   | Prefix          | DNS Name   | Text    |

### On the PVE API

You'll need to create a dedicated user (ex: netsync) on your PVE cluster and then create an API token.

The user needs to have access to the VM.Monitor, Pool.Audit, VM.Audit, Sys.Audit permissions.

The following env variables will need to be set:

- **PVE_API_HOST**: The DNS/IP to your PVE instance. (ex: 10.10.0.10)
- **PVE_API_USER**: The username of the account created previously. (ex: netsync@pve)
- **PVE_API_TOKEN**: The name of the API token created previously. (ex: test-token)
- **PVE_API_SECRET**: The API token created previously (ex: 4d46dc0a-6363-47a2-98df-d5cdfefa33d2)

### Executing the legacy script

Supply the documented legacy environment through a protected process manager or secret
facility, then run `nbpxsync`. Do not embed credentials in shell history or repository
files.
