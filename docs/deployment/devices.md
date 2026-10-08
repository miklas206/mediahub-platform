# Optional host device requirements

Status: Phase 4 foundation, not a passthrough manager. No device is attached,
detached, initialized, repaired or granted to an application by these checks.

Reusable manifests declare logical requirements, not installation-specific IDs:

```yaml
requiredDevices:
  - id: archive
    type: block
    selectorRef: archive_disk
    required: true
    missingHealth: critical
```

`type` supports `usb` and `block`; `missingHealth` supports `degraded` and
`critical`. USB selectors use vendorId/productId plus serial where available.
Block selectors support serial, UUID and stableIdentity matching. The host snapshot
collector reports UUIDs; the sysfs-only fallback reports serial metadata only.
Never substitute `/dev/sdX` or USB bus/device numbers for stable identity.

Agent configuration (installation-specific, backend-side):

- `MEDIAHUB_AGENT_USB_SYSFS_ROOT`: explicitly exposed host USB sysfs directory.
- `MEDIAHUB_AGENT_BLOCK_SYSFS_ROOT`: explicitly exposed host block sysfs directory.
- `MEDIAHUB_AGENT_DEVICE_SNAPSHOT_FILE`: protected host-generated JSON snapshot;
  takes precedence over block sysfs. Invalid or older-than-90-second data is unavailable.
- `MEDIAHUB_AGENT_REQUIRED_DEVICES`: JSON array of logical DeviceRequirement objects.
- `MEDIAHUB_AGENT_DEVICE_SELECTORS`: JSON object keyed by selectorRef.

All defaults are empty/unconfigured. Physical IDs are not supplied by the shared
catalog. Any container sysfs view must be read-only and preserve the necessary
symlink targets; a container-only view must not be mistaken for host inventory.
No `/dev` nodes, privileged mode or device write access are needed for discovery.

Example fictional selector (not a real deployment):

```json
{"archive_disk": {"serial": "example-installation-disk"}}
```

Authenticated `/v1/status` includes `devices.sources`, `devices.checks`,
`devices.requiredCount` and `devices.health`. Core preserves this in host metadata.
Missing, inaccessible, unconfigured or ambiguous required identity fails closed
to its configured severity. One matching identity yields Connected. A healthy
empty requirement list means no requirements configured, not that hardware was
verified. Optional missing devices are unknown. Agent liveness remains separate
from device readiness, so management remains reachable to diagnose missing disks.

USB enumeration reads at most 256 sysfs entries. The optional host-side collector
`agent/device_snapshot.py` uses bounded `lsblk` and host mountinfo, reporting model,
size, serial, UUID, by-id aliases, stable identity, mount paths and mount read-only
flags. It does not mount/unmount devices or modify them. Its only write is an atomic
metadata snapshot. Run it in the HOST mount namespace: do not enable systemd
ProtectSystem/PrivateMounts or infer host mounts from a container mount table.
Use a protected, setgid directory owned root:agent-read-group, mode2750; snapshot640.
The Agent receives that directory read-only, not device nodes or extra capabilities.

`mountRequired` and `writeRequired` add readiness checks to a block requirement.
Set installation selector `mountPath` to require the expected mount location.
Mount RW flags do NOT assert the app UID has filesystem write permission. Device presence
is not proof of filesystem correctness, required mount, write permissions or free
space. Storage validation must be an additional startup and runtime gate.

The Phase 4 Agent and Core metadata consumer now have device reporting deployed.
Core exposes `deviceHealth` separately from online/offline management connectivity;
offline hosts have unknown deviceHealth, not cached Healthy. App health/lifecycle
gates and UI rendering still require integration. Per-host configuration currently
lives in the Agent deployment environment, not a configuration UI.
An NFS-only test Seedbox must not be made dependent on an old production USB disk.
