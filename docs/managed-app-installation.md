# MediaSeed and MediaVPN installation

The App Store exposes administrator-only installation pages at `/store/mediaseed`
and `/store/mediavpn`. The old dedicated-Agent Seedbox guide remains available at
its original route but is no longer the setup action for the independent app.

`GET /api/v1/managed-install/<package>` validates the host recipe and returns an
opaque plan digest and operation status. HTTPS/admin/CSRF-protected POST accepts
only that digest. It never accepts Docker specs, host paths, images or secrets.
Background operations share the managed-app lifecycle lock and resume after Core
restart. Existing containers must match the approved project, image, configuration
and mount bindings. Installation does not delete containers or volumes. Successful
health checks clear the previous removal state and restore the app registry/SSO.

## Host preparation

Install recipes are operator-owned runtime configuration, not promoted source.
The host must have approved app images, data volumes, networks, TLS, app origins
and Compose ownership prepared. This change does not download arbitrary images,
grant Docker-host access, invent TLS certificates or configure a user's VPN.
Fresh hosts without this preparation receive an explicit unavailable error.

Export an existing approved Compose deployment with the read-only preparation
script (substitute the current Core data mount and UID/GID):

```sh
python3 scripts/prepare_managed_install.py \
  --policy /opt/mediahub/managed-apps.json \
  --data-dir /opt/mediahub/data --container-data-dir /data \
  --uid 10001 --gid 10001
```

The script inspects existing Compose projects, pins exact local image IDs, skips
completed initialization jobs, and writes private recipes under the Core data
directory. It starts/stops/deletes nothing. Restart Core after preparing recipes
so its read-only managed policy is reloaded. Do not copy these recipes, TLS files,
private data or runtime settings from beta to main. Prepare each host separately.

MediaSeed downloads stay blocked until the app verifies a selected VPN. Installing
MediaVPN does not connect a tunnel or implicitly connect MediaSeed. Existing
credentials, profiles, accounts, sessions and downloads remain in their mounts.

## Recovery

Operation journals contain state and sanitized messages, never Docker recipes or
environment credentials. Failed/partial installations remain available for retry;
data volumes are never recreated when missing. Fix the host/image/health issue and
review a new plan before retrying. Existing app removal retains the prepared recipe
so the same app can be installed again without replaying initialization jobs.
