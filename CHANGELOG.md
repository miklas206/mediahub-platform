# Changelog

## 0.6.68

- Preserve the polling notification fixes from 0.6.67 and give explicit app-address/resource action failures priority over an older background-read error, so new failures remain visible during an outage.

## 0.6.67

- Keep expired healthy Plex, Seedbox and Cloudflare observations explicitly cached instead of manufacturing failing runtime checks during normal polling. Genuine failures and connection errors remain visible.
- Stop repeated identical error popups across app settings, resources, storage, shared VPN, Plex/Jellyfin account/domain setup: retain unresolved errors until recovery and share slow in-flight reads. Preserve path isolation, cancellation, bounded retries and server-side action validation.
- Apply the same frontend behavior on fresh installations and upgrades; no managed-app restart, media migration, credential or database schema change is required by this fix.

## 0.6.65

- Identify Plex explicitly when it must be stopped for a shared NAS write-cache change. Stopped MediaSeed/MediaVPN apps no longer receive a misleading instruction to stop themselves when Plex is the blocker. Preserve running-app and storage ownership checks.

## 0.6.64

- Enable MediaSeed's NAS write cache without removing existing app bindings or Windows shares. Validate stopped apps, preserve shared mount parents, and restore NAS views and authenticated Windows shares after the cache transition. Existing local download mounts remain available.
- Apply the same transition to fresh installations and existing uncached NAS connections; retain NAS identity, credentials, media and the selected persistent cache on retries.

## 0.6.63

- Report Plex remote access from its active shared VPN and separate public port instead of the unused dedicated VPN. Require matching profile, endpoint and fresh public identity verification before showing the port as ready.
- Fix shared VPN Agent routes after the app-storage lock was added: enter the HTTPS/storage dependency correctly so status, configuration and Plex port reconciliation work again.
- Automatically hide completed installation progress for Plex, container apps, MediaSeed/MediaVPN and legacy installers; retain active progress and failure details.

## 0.6.62

- Show Start app in green, including its icon, hover and keyboard focus states; retain the stop action styling.
- Fix NAS attachment to Plex and other apps sharing a VPN network namespace. Remove inherited inspect-only hostname and image port declarations from recreation requests while preserving the actual network, image, mounts and settings. Applies to existing containers and fresh installations without moving media.

## 0.6.61

- Prepare the host media group before installing or starting the storage controller. Numeric systemd Group=1000 requires a host group entry even when media files already use that GID; without it the controller failed with 216/GROUP and app settings stayed on Preparing storage.
- Backfill the missing group automatically on fresh installs and upgrades, reuse existing GID 1000 without changing accounts or media ownership, and reject conflicting group names with a concrete prerequisite.

## 0.6.60

- Fix intermittent update rollback caused by changing SQLite WAL/SHM files; snapshot committed database state through SQLite and preserve configuration ownership.
- Retry transient Core update failures up to three attempts with backoff, one operation identity and verified recovery before retrying. Permanent validation/disk/permission failures and failed rollback stop immediately.
- Exclude stale/deferred and already-current checks from Update all, retain readable versions alongside commit identities, and report verified manual upstream releases separately.
- Fix Plex startup after restart with installation storage policies, and recover verified publisher identity after storage changes for read-only image update checks.
- Switch stopped app cards to Start app and show Not running instead of a critical status.

## 0.6.59

- Add explicit NAS attachments for MediaSeed and Plex under Storage and app settings, with a Danish Plex library guide and preserved existing media/settings.
- Keep MediaSeed, qBittorrent and the VPN client mappings aligned across app/Core updates; give Plex a separate read-only view and guard startup with fresh host NAS evidence.
- Prepare torrent-compatible FUSE write caching on verified separate media storage, preserve pending uploads, and propagate NAS reconnections into existing app containers.
- Require stopped apps for mount changes; preserve runtime settings, install recipes and private recovery data, with a guided restore action after interrupted changes.

## 0.6.58

- Correct NAS capacity reporting with a verified, pinned SMB client. Older distribution rclone versions can report half the real capacity on NAS filesystems with larger sectors. Query existing FUSE mounts through the corrected SMB client without interrupting open connections.
- Prepare the architecture-specific, checksum-verified client automatically for fresh installs and upgrades, preserving NAS credentials and mounts. A failed capacity query shows capacity unavailable without falsely marking the NAS disconnected.

## 0.6.57

- Identify a completed update queue as previous when a different, newer Core update operation is displayed. Preserve both results and their logs without implying the newer attempt succeeded.
- Retain bounded failure diagnostics in a root-private directory, with only the exception type in public update logs, so intermittent snapshot/update failures can be traced without exposing command output or credentials.

## 0.6.56

- Replace the inverted NAS read-only checkbox with Allow changes on the NAS and plain-language explanations. Preserve the existing saved access mode.
- Automatically prepare userspace SMB mounts for unprivileged Linux containers, using private config and independent managed mount services. Retain native CIFS on ordinary hosts.
- Prepare FUSE in new Proxmox installations and provide an idempotent device-only preparation helper for existing containers, preserving other devices and avoiding container restarts. Saved connections retry after prerequisites become available.
- Allow correcting a disconnected NAS login without removing its connection, and explain automatic retries.

## 0.6.55

- Group local subfolders beneath their media storage root and show shared filesystem capacity once. Keep separate NAS mounts and Windows sharing choices available.

## 0.6.54

- Match Storage read-only controls to the height of adjacent inputs and align them with the input row, preserving checkbox behavior.

## 0.6.53

- Exclude the live storage-control Unix socket directory from configuration snapshots and preserve its inode and connection across rollback. Keep persistent storage state, credentials and app data unchanged.
- Verify both successful upgrades and forced rollback with a real listening Unix socket.

## 0.6.52

- Offer the verified media mount root in Settings → Storage so a Windows share can include all subfolders, preserving existing folder shares and app mappings. Prepare the additional choice automatically on fresh installs and upgrades.
- Add comfortable padding around storage panels and forms at desktop and mobile widths.

## 0.6.51

- Add administrator-only Settings → Storage, with approved local-folder capacity, saved SMB3 NAS mounts, and authenticated Windows shares with a per-share connection guide.
- Refresh the checked-in API contract, including the new storage operations.
- Keep host operations in a private Unix-socket controller installed through the supported Linux installer and the existing root updater. Backfill the controller on upgrades without replacing app credentials, storage policy, media or disabled NAS intent.
- Mount NAS shares at fixed private targets using root-only credentials, verify the live mount identity, and refuse system-disk fallbacks or busy forced unmounts. Windows shares default to read-only and bind only to the configured private LAN address.
- Preserve previous SMB service configuration on failed replacement; keep Windows passdb credentials separate from NAS and MediaHub login. Existing app mappings are not implicitly changed.
- Verify synthetic install/upgrade and authorization paths, responsive browser workflows, and isolated SMB authentication/read-only access. Real NAS mounts still depend on the host's CIFS capability, including explicit Proxmox/LXC permission where required.

## 0.6.50

- Keep the public proxy source visible when Docker uses its userland proxy for same-bridge published ports. Prepare a narrowly scoped owned ingress translation alongside the LAN/WAN rules and remove all three on disconnect.

## 0.6.49

- Preserve independently selected Plex and public-gateway VPN profiles. Keep public forwarding on the approved private listener and reconcile separate bounded LAN/client and Docker/public-proxy translation rules, preserving remote classification without requiring a shared WireGuard namespace. Migrate the previous LAN rule automatically and preserve unrelated NAT rules.

## 0.6.48

- Route the dedicated public Plex TCP proxy to the verified app WireGuard address, keeping external traffic separate from the local published listener and its LAN recognition rule. Preserve Plex authentication and the existing public lease/publication verification.
- Expose the private relay address only for a ready, owned app namespace. Older Agents without that evidence show an update prerequisite instead of silently using the LAN endpoint for public forwarding.

## 0.6.47

- Preserve current application mounts, environment, resource settings and migration labels when reapplying a shared VPN namespace. Restore only the original networking fields instead of replacing the latest app specification with a stale copy.
- Verify Plex's actual transcode bind mount and TMPDIR before reporting temporary storage ready. Automatically repair an incomplete 0.6.46 mapping when playback is idle, even if its saved migration receipt says complete; roll back if container creation drops the required mapping.
- On unprivileged Linux hosts, prepare execute-only directory ACLs for the namespace's Docker root so it can attach the private Temp bind. Preserve file permissions and existing ACL grants; reject an incompatible existing mask instead of broadening other users' access.
- Prepare a bounded LAN-only source-NAT rule for Plex behind the shared VPN relay, so clients on the host's verified local subnet are classified locally without changing Plex authentication or requiring a new LAN address. Keep external/VPN ingress outside the rule, reconcile it on fresh installs and upgrades, and remove only the owned rule on VPN disconnect/removal.
- Report local-access preparation separately from temporary storage. A full underlying app-data disk still requires storage repair; aggregate free pool space alone is not proof that existing cache/metadata directories are writable.

## 0.6.46

- Select approved temporary transcoding storage separately from Plex movie, TV and other libraries. Default to a dedicated `Temp/<installation>/work` directory on the selected app-data storage, prepare it as the app user and configure Plex automatically.
- Add the missing temp mapping to older managed installations when playback is idle, using the installed Plex image and a recoverable container replacement. Preserve custom transcoding paths, account settings, libraries, stopped intent and media.
- Verify actual file allocation as well as free space. Let Plex clean finished sessions; clear only owned orphan session directories while Plex is stopped, retaining unrelated files and rejecting symlinks.

## 0.6.45

- Publish the verified Plex public HTTPS endpoint independently of the server's detected outbound VPN IP. Follow verified public IP/port changes, preserve the LAN endpoint and other custom URLs, and remove only the managed public URL when forwarding is disabled.

## 0.6.44

- Automatically advertise the approved Plex LAN HTTPS endpoint using its own certificate identity, including existing installations and later address changes. Preserve other custom URLs and encrypted preference recovery.
- Add managed Jellyfin domains through the existing MediaVPN DNS/HTTPS gateway, alongside Plex, without enabling previously disabled routes or changing other apps.
- Document the distinction between discovery, Plex LAN classification, remote routing and client codec support. These changes do not certify Xbox 4K/Atmos playback or automatically override Jellyfin's saved transcoding preferences.

## 0.6.43

- Refresh Plex remote-access publication after a verified public IP or port changes. Send Plex client identity headers, retry a failed refresh on the next reconciliation, and backfill publication for older receipts without rewriting user preferences.

## 0.6.42

- Bundle MediaVPN 0.2.30: verify Plex forwarding against its own lease helper so Plex-only remote access is advertised without requiring a torrent helper. Preserve fail-closed checks for stopped, stale or mismatched helpers.

## 0.6.41

- Manage Plex remote access independently of public app domains. Use the existing shared VPN profile and a dedicated renewed Proton TCP lease; verify the public Plex server identity before reporting success.
- Bundle MediaVPN 0.2.29 with support for a Plex-only gateway without Cloudflare credentials or an HTTP listener. Existing disabled domain choices stay disabled; fresh installs and upgrades require no manual configuration migration.

## 0.6.40

- Bundle MediaSeed 0.1.26 and MediaVPN 0.2.28: progressive torrent/RSS/VPN dialogs in MediaHub themes, extension dialog/RSS handoff, pooled internal requests, batched background torrent observations, and retained stale tracker/torrent displays.
- Load secondary settings/runtime pages on demand, retain app-page observations across navigation, and request independent app VPN statuses concurrently.
- Existing profiles, app assignments, credentials, storage and seeding policies are preserved; new RSS cleanup fields are optional for older feeds. User installs this source release; no live migration or restart was performed.

## 0.6.39

- Select apps on individual MediaVPN connections with persistent profile assignments and isolated relays. Bundle MediaVPN 0.2.27, temporarily hide Apps and domains, and provide an explicit app-assignment reset that retains profiles and media.

## 0.6.38

- Match Overview and Settings to the Apps page 1440-pixel content width. Remove viewport-driven text enlargement while preserving responsive mobile spacing and existing navigation.

## 0.6.37

- Provision approved Other media locations for independent apps on fresh installation and upgrade. Recover a missing Other entry from the existing Plex approval only when storage identity anchors match, without changing credentials, media or explicit app policy.
- Automatically adapt the main workspace to screen width, up to 2400 CSS pixels, with fluid text and spacing. Keep the existing navigation choices and mobile layouts.

## 0.6.36

- Resolve Overview host RAM capacity from the local Docker daemon instead of LXCFS meminfo virtualized to the 64 MiB sampler. Refresh capacity every 15 seconds with bounded requests and reject unverified/inconsistent observations. Existing 0.6.35 snapshots are corrected immediately without a sampler restart; fresh installs and upgrades use the same path.
- Restrict Overview resource cards to local owned apps. External Cloudflare monitoring and remote hosts are excluded. Measure Core, proxy, Agent and resource sampler separately, and show named VPN helper components once. Clarify OS overhead and different sampling intervals; show CPU core equivalents beside the percentage.
- Show system disk use and free space separately from media storage. Automatically provision a read-only host OS file bind into the sampler; no host directory is created if the source is missing.
- Healthcheck cleanup reports dynamically formatted reclaimed space in its completion popup, operation details and persistent last-result view. Persist a single before/after free-space pair and signed change; missing measurements remain unavailable. Cleanup scope and preservation rules are unchanged.

## 0.6.35

- Overview CPU/RAM now report the complete local Docker host (the MediaHub LXC on Proxmox), including Core, apps and shared services. A restricted read-only sampler is provisioned automatically for new and existing installations without recreating apps. Missing or stale host measurements are explicitly unavailable; Core limits are never presented as host capacity. Media storage retains the configured storage pool scope.
- App RAM discounts active and inactive file cache, matching the Proxmox accounting convention more closely. Version the history accounting key so old cache-inflated peaks cannot generate recommendations using the new definition. Show the roughly one-minute app sampling interval in Overview.

## 0.6.34

- Reuse the selected MediaSeed app image for its one-shot client initialization instead of issuing a second build. Apply the shared image configuration idempotently to fresh and existing approved Compose projects, preserving initializer entrypoint, user, isolated networking, volumes and secrets. Initialization still runs its existing compatibility checks and cannot pull a replacement image.
- Bundle MediaSeed 0.1.12 and MediaVPN 0.2.17 for fresh installations. Their Dockerfiles separate a stable dependency manifest from version metadata and application sources, so unchanged dependencies can reuse Docker layers. Installing changed application code uses existing build tools without resolving dependencies or accessing a package index. Existing apps keep their independent update versions.

## 0.6.33

- Replace Overview's app list with measured per-app CPU cores, RAM working set, saved limits and observed peaks. Keep shared VPN infrastructure separate; stopped torrent templates are not counted twice. Unsupported runtimes show the required Agent/app upgrade instead of invented measurements.
- Add administrator-only manual resource edits on Overview and app settings, plus opt-out per app. Validate installation revision, host capacity, memory headroom and CPU affinity; persist limits before applying live Docker changes, verify the result and restore previous limits on failure. Journal interrupted operations without automatically repeating mutations.
- Add persistent five-minute peak history, proposals for repeated pressure over an hour and conservative reductions after seven days with at least 80% coverage. Proposals require explicit approval and are checked again when approved. Fresh installs and existing versions initialize history automatically without resetting credentials or media.
- Bootstrap MediaVPN 0.2.15 on fresh installs so recreated torrent clients inherit saved limits. Existing apps still update independently; MediaSeed editing explains when MediaVPN needs updating. Core updates preserve existing app versions and resource configuration.

## 0.6.32

- Check Core, Agent, MediaSeed and MediaVPN main-branch versions using read-only Git instead of GitHub REST metadata. Reuse the existing repository-bound Core deploy key; otherwise use verified Git HTTPS with the existing encrypted token or anonymous public access. Share bounded five-minute metadata results and brief failure backoff by repository and credential identity. Credentials never enter Git URLs, command arguments or on-disk Git configuration. Existing source downloads, individual updates and rollback remain unchanged. Git and CA certificates are already provisioned by the Core image for fresh installations and upgrades.

## 0.6.31

- Route independent MediaSeed/MediaVPN version checks through the same bounded GitHub metadata cache and provider cooldown as Core and Agent. Repeated checks reuse main metadata for five minutes and immutable project metadata for one hour; a rate limit on one component pauses other uncached checks sharing the credential identity. Installed versions and separate app repositories remain independent. No deployment or credential migration is required.

## 0.6.30

- Give MediaSeed and MediaVPN their own repository checks and selected-app source updates, with persisted operations and restart recovery. Core preparation preserves existing app images and versions while applying required configuration repairs. Fresh installs bootstrap MediaSeed 0.1.9 and MediaVPN 0.2.14; existing installations update apps individually.
- Include the richer MediaSeed torrent/RSS interface for fresh installs and remove the fixed beta badges from both apps.

## 0.6.29

- Persist Plex/shared-VPN controller decisions and bundle MediaVPN 0.2.13 with owner-scoped passive Docker lifecycle observation. Retain safe causes, operation IDs, provider/container generations, exit/OOM evidence, changed ports and verification stages across container replacement. Settings Logs aggregates durable diagnostics; existing Plex logs also survive restart. Fresh installs and upgrades initialize journals automatically in existing persistent data directories without changing media or credentials.

## 0.6.28

- Fix false relay health failures between normal WireGuard rekeys while rejecting expired sessions. Bundle MediaVPN 0.2.12: independent torrent mapping revision and consistent observed generation prevent unrelated Plex/web changes from recreating the torrent client.
- Bundle MediaSeed 0.1.7: explain the retained private RSS link, display the saved start date and verify the server date receipt before resetting the edit form. Existing URLs are preserved on blank-field edits.

## 0.6.27

- Bundle MediaSeed 0.1.6: reconcile a stale MediaSeed-owned qBittorrent RSS item when the same feed is recreated with a new ID. Remove only exact-URL duplicate RSS registrations no longer referenced by any configured feed; preserve torrents, media and other RSS items.

## 0.6.26

- Bundle MediaVPN 0.2.11: identify RSS torrent metadata requests with the observed qBittorrent version, avoiding tracker rejection of Python default requests. Keep bounded responses, HTTPS/host validation, disabled redirects and verified VPN gating.

## 0.6.25

- Bundle MediaSeed 0.1.5 and MediaVPN 0.2.10: accept both current /torrent/download/ and legacy /torrents/download/ RSS links on the approved tracker. Preserve HTTPS/host/path validation, duplicate history, storage selection and fresh VPN gating.

## 0.6.24

- Move the home-card stop control into the action row, with a compact stop icon, quieter styling, keyboard focus and explicit stopping feedback. Preserve confirmation and runtime behavior.

## 0.6.23

- Keep local MediaSeed/MediaVPN login on the approved LAN origin even when a public domain is saved. Carry the selected allowlisted origin through hub authorization and login resume. Bundle MediaVPN 0.2.9 and MediaSeed 0.1.4.
- Read accepted VPN configuration and the current provider endpoint after applying a gateway change; never use the pending write acknowledgement as a verified public address. Include the accepted Plex target in the machine acknowledgement.
- Add confirmed Stop app controls on home cards and common runtime panels on app status pages. Managed stop/start preserves the owned running-container selection, excludes inactive original clients when resuming a VPN client, and preserves media/configuration. Managed logs show retained lifecycle events. Updates use existing app/Core update workflows.

## 0.6.22

- Expand app settings into live status pages with health, installed version, owned containers, local/domain links and address editing. Preserve Plex-specific setup and managed domain controls, adding its addresses and uptime.
- Show separate local and configured domain links on installed app home cards, including available catalog apps. Count uptime from confirmed runtime start, reset on restart, stop on shutdown and show unknown when observations expire or are unavailable.
- Extend the existing Agent status schema and managed app inspection with start timestamps. Preserve existing installations and settings; no database migration or additional dependency is required.

## 0.6.21

- Restore standard heading and content spacing in Plex account and VPN domain panels. Align actions, wrap long domains and translated card text, and pad ordinary users app cards. Translate the MediaVPN opening link into Danish.
- Add rendered text containment checks across hub settings/install screens and standalone app tabs/dialogs at desktop, tablet and mobile widths. Preserve intentional table scrolling and filename ellipsis.

## 0.6.20

- Show a success popup with a direct Plex configuration link after verified account linking. Keep the next-step guidance on the page after the popup closes; do not repeat the popup when opening an already linked server.

## 0.6.19

- Add guided Plex account linking after installation and on the existing server page. Request a fresh short-lived token only after the image download. Apply it through the existing protected RAM configuration and container claim mechanism, verify the claim, encrypt updated preferences, and clear the token on success or failure. No browser SSH setup is required.
- Reset saved opening addresses and selected gateway domains after confirmed app removal. Upgrade older uninstalled Plex/Jellyfin/Seedbox registrations, queue ownership-checked DNS cleanup, and preserve active apps and media.
- Bundle MediaVPN 0.2.8: hide Plex forwarding for uninstalled servers and refresh domain drafts when confirmed server selections change.

## 0.6.18

- Restore the exact approved, published hub VPN domain during startup. Host validation and SSO no longer wait for the first Cloudflare/VPN reconciliation after an update. Disabled and unconfirmed domains are not added.

## 0.6.17

- Open Plex Web directly at `/web/index.html`. Avoid Plex's `/web` redirect to an HTTP URL behind the HTTPS VPN gateway, which otherwise reaches a different route and returns 404.

## 0.6.16

- Open Plex settings on the actual installation page. Use the installed server's saved domain or approved local address with `/web`, instead of falling back to Plex account-wide web settings.
- Add managed Plex domain selection on its installation page. Merge only that app's selection into the existing VPN gateway configuration, reject concurrent changes, and keep DNS/certificate/IP management in the existing gateway. Guide fresh installations through prerequisites.
- Surface the server's Plex account claim status and explain unfinished setup before remote access.

## 0.6.15

- Bundle MediaVPN 0.2.7. Validate API response types and JSON decoding, preserving actionable endpoint and HTTP status errors instead of exposing JSON parser errors. Never replay an activation automatically after an invalid response.
- Preserve the last successful app status if one gateway status request fails, avoid repeating the same background notification until recovery, and continue live updates without collapsing open sections.

## 0.6.14

- Restrict shared VPN transformation to the real Plex server. Recover owned stopped preparation helpers while preserving isolated helper networking, entrypoints and app data. Keep saved Plex start intent across interrupted VPN changes and inspect the installed server name for status.
- Bundle MediaVPN 0.2.6: preserve expanded sections and edits during automatic status updates every five seconds, with immediate refresh on return to the page. Status polling only reads existing endpoints.

## 0.6.13

- Bundle MediaVPN 0.2.5. Restore Settings beside Sign out, with appearance controls in the existing dialog. Keep Cloudflare as its own workspace tab alongside Connection and Apps and domains.
- Preserve existing theme preferences, Plex SSO fixes and DNS ownership during updates.

## 0.6.12

- Add the missing administrator-scoped MediaVPN SSO endpoint for Plex remote access. Preserve actionable prerequisite errors through the actual app-to-hub request path.
- Keep requested DNS records and Origin Rule hostnames when an app is temporarily unavailable during updates or restarts. Restore forwarding automatically when the app returns; explicit route removal, disabling and confirmed uninstall still clean up owned resources.
- Report unfinished Plex account setup explicitly before applying remote-access settings.

## 0.6.11

- Bundle MediaVPN 0.2.4. Replace the generic Settings tab with separate Cloudflare and Appearance tabs, and remove the duplicate settings button from the header.
- Render existing appearance controls directly in the Appearance panel, preserving automatic theme saving and account overrides. Support four-tab keyboard navigation and a two-column layout on small screens.

## 0.6.10

- Bundle MediaVPN 0.2.3. Remove the legacy fixed app-connection summary that flashed before gateway loading completed. Keep app connection controls in the Apps and domains tab, including the compatibility fallback.
- Refresh localization asset versions so new tab and detail labels use the selected account language.

## 0.6.9

- Redirect the removed standalone Apps page to the hub home and send app return links directly home.

- Allow Docker to traverse only the owned Plex persistent mount directories on FUSE storage in unprivileged Proxmox containers. Keep files, encrypted preferences and media permissions unchanged. Prepare fresh installs and repair older directory modes before runtime starts.
- Recognize recovery of an installation blocked at container start only after matching runtime ownership, running state and mounted storage are verified.

## 0.6.8

- Bundle MediaVPN 0.2.2 with compact Connection, Apps and domains, and Settings tabs. Render profiles before slower gateway checks; prevent overlapping refreshes and retain setup drafts.
- Add optional, separate Proton TCP forwarding for installed Plex servers attached to the shared VPN. Automatically prepare the relay dependency on fresh installs and upgrades.
- Verify the public Plex server identity before reporting remote access ready; renew only the owned lease and block forwarding when provider state becomes stale. Preserve and restore previous Plex remote-access settings when disabling the feature.

## 0.6.7

- Migrate old Plex removal receipts when the verified owned runtime is absent. Reset only owned configuration before a fresh reinstall.
- Recover stopped, owned Plex preparation helpers and partial configuration scaffolds. Fresh reinstalls create new preferences instead of requiring deleted encrypted identity records.

## 0.6.6

- Map TUN into the MediaVPN management container on fresh installs and when updating existing Compose configurations. Preserve saved profiles, credentials and app domains.
- Bundle MediaVPN 0.2.1. Gateway activation continues to require a character device that can actually be opened; missing host/LXC TUN access remains an explicit prerequisite.

## 0.6.5

- Let old completed Plex/Seedbox removal receipts be confirmed again to reset settings preserved by previous versions.

## 0.6.4

- Reset app settings, accounts, VPN profiles and owned configuration when uninstalling MediaVPN, MediaSeed, Plex and managed container apps. Keep media and downloaded files.
- Clear saved Hub app configuration after verified removal, and require Agents to verify the configuration reset before reporting success.
- Block reinstall after an incomplete reset; allow bounded cleanup retries. Preserve host provisioning and integration identities for fresh app setup.
- Explain the fresh-install behavior in the removal confirmation and progress UI.

## Unreleased

## 0.6.3

- Fence Plex/Jellyfin VPN reconciliation before uninstalling, remove verified app relays, and remove the matching shared-gateway peer before forgetting the hub installation binding.
- Show obsolete VPN connections for apps confirmed uninstalled, with explicit, snapshot-confirmed cleanup. Reject active containers, changed snapshots, foreign ownership and namespaces used by other containers. Preserve VPN profiles, keys, media, volumes and app data.

## 0.6.2

- Restore app VPN connection controls on the MediaVPN setup page so apps can be disconnected before uninstalling the VPN runtime. Keep provider/domain configuration in MediaVPN.
- Explain blocked removal persistently in the confirmation dialog and link directly to connection controls. Continue enforcing dependency checks on removal requests; do not disconnect or delete anything automatically.

## 0.6.1

- Show durable Plex installation phases and progress on its installer and runtime page, including indeterminate image downloads, reconnecting, failure and confirmed completion.
- Add progress bars to FjordHub and the legacy Seedbox wizard; restore the active FjordHub deployment step after reloading. Show immediate activity for all five container-app installers and keep MediaSeed/MediaVPN polling through connection failures.
- Allow confirmed removal of failed or interrupted Plex installations before a managed runtime policy exists. Verify the saved identity and container ownership, preserve media, app data, volumes and credentials, and verify containers are gone before removing the hub registration. Retry removal status after temporary connection failures.

## 0.5.36

- Add guided Proxmox host GPU driver/firmware preparation to fresh installation and existing-instance GPU setup. Offer matching kernel headers, DKMS, NVIDIA NVENC/NVDEC libraries and Intel/AMD firmware, with explicit host-package/repository confirmation and APT removal protection.
- Reuse functioning drivers, pin missing NVIDIA video libraries to the running driver version, preserve VFIO/VM assignments and stop for kernel/Secure Boot/reboot recovery instead of unloading live drivers or rebooting the node. Continue with existing guest runtime installation and hardware-encoding verification after the host is ready.

## 0.5.35

- Fix the in-app GPU test rejecting the official Jellyfin image's automatically created `/config` and `/cache` volumes. Override those paths with bounded tmpfs in both UI and CLI tests, retaining the ban on disk volumes, bind mounts and unapproved mounts.
- Verify tmpfs configuration explicitly and cover Docker's inspected tmpfs mounts in regression tests. No app media or credentials are mounted, and no permanent test volumes are created.

## 0.5.34

- Limit NVIDIA video grants to the selected GPU, control and UVM devices. Administrative capability and display nodes are not required for ordinary NVENC/CUDA and can be root-only after NVIDIA runtime initialization.
- Add an explicit repair mode for existing GPU setups. Back up and reduce the matching inventory/policy/controller mappings, retain external media mounts and other services, recreate only Core/Agent with no dependencies and run hardware verification without stopping the LXC or Docker.
- Show the repair choice inside the GPU guide and report the actual denied device names when controller access fails.

## 0.5.33

- Fix NVIDIA discovery incorrectly reporting a missing Proxmox driver because `minor_number` is not a supported nvidia-smi query field. Query the PCI bus ID and verify the UUID/device minor against kernel GPU information; never assume the GPU index equals its device node.
- Point the in-app preparation command at the corrected GPU tools and stop with diagnostics when no ready GPUs are detected.

## 0.5.32

- Fix Core reporting 0.5.28 in releases 0.5.29-31, which caused the host updater to reject requests against the newer installed-version marker. Add a release consistency regression check.
- Add narrowly scoped host-helper recovery for those versions, requiring the installed source commit, running Core revision and project metadata to agree. Keep rejection of unrelated version/commit mismatches and show an actionable version-error diagnostic.

## 0.5.31

- Add a resumable GPU setup wizard under Settings → General and link it from Jellyfin installation. Show Proxmox preparation steps inside MediaHub, then detect approved devices and carry the tested host/GPU into Jellyfin setup.
- Run a real synthetic hardware-encoding test through the selected Agent with progress and logs. Use an owned disposable Jellyfin container with no media mounts or networking, exact approved GPU devices, bounded resources and cleanup; never report CPU fallback as GPU success.

## 0.5.30

- Bundle MediaSeed 0.1.2 with RSS storage-location selection and existing-folder browsing, including mount capacity and Unicode folder names. Persist the location on each feed and use the approved destination for RSS categories and torrent imports.
- Validate feed destinations when saving, enabling and importing; block unavailable/read-only targets without falling back to local disk. Preserve legacy feed paths and existing torrent data. Refresh browser asset URLs so the updated form loads after upgrading.

## 0.5.29

- Add optional GPU discovery/selection to the Proxmox installation guide. Share only approved render/NVIDIA nodes, stage matching NVIDIA host driver libraries read-only and prepare the guest Docker NVIDIA runtime without changing host kernel drivers.
- Add an explicit GPU transcoding choice to Jellyfin installation and include the device selection in reviewed plans. Preserve GPU requests and supplemental groups through restart and VPN recreation; reject unavailable or revoked grants.
- Document preparation of existing MediaHub guests and the separate Jellyfin hardware-acceleration setting. Keep CPU-only plan digests and requests compatible with existing installations and Agents.
- Add a guided existing-instance GPU tool with explicit downtime confirmation and a diagnostics-only mode. Verify controller device access and an actual synthetic hardware encode in an isolated official Jellyfin container; report failure without CPU fallback and clean up only the owned test container.

## 0.5.28

- Keep the home-page app card named MediaSeed before installation and after removal, as well as while installed or connected. Retain the existing package aliases and setup paths.

## 0.5.27

- Show installation progress for Jellyfin and the shared container-app installer immediately after acceptance and through server status after a page reload. Use an indeterminate bar during publisher-image download, followed by explicit storage, creation and startup phases.
- Forward bounded progress fields through the public Agent status schema. Preserve the phase on failures and report 100 percent only after the created container is inspected as running; retain unknown application health until separately verified.

## 0.5.26

- Fix automatic app preparation in unprivileged LXCs by inheriting the owned Core container's supplementary groups. Host evidence with an unmapped owner remains protected and readable through its approved group; no host file permissions change.
- Stamp the actual bundled version on app containers and report it in update checks. Explain Core-delivered updates and show failed/preparing state with an explicit retry action on the Updates page.
- Recheck bundled app versions after preparation completes. Keep completed client initialization and a deliberately stopped source qBittorrent from marking a healthy VPN-bound MediaSeed installation unknown.

## 0.5.25

- Add a storage location and existing-folder browser to MediaSeed torrent imports, shared by magnet and file uploads. Report capacity and writable/unavailable state separately for the local volume and approved media/download mounts.
- Provision approved media binds to both MediaSeed and qBittorrent while retaining existing download volumes, host permissions and all media. Require current host mount evidence and storage identity markers; never create missing host bind directories.
- Reuse those exact verified binds in MediaVPN's torrent client, refresh it when its storage configuration changes, and support Unicode/spaces in safe download paths without relaxing the VPN gate. Bundle MediaSeed 0.1.1 and MediaVPN 0.1.3.

## 0.5.24

- Replace Cloudflare tunnel creation/connector/route controls with read-only tunnel inventory and VPN-bound DNS creation. Reject new tunnel creation through the API; retain existing resources and pause legacy scheduled ingress synchronization.
- Create DNS-only A/AAAA records from verified MediaVPN profile public IPs, with automatic IP-change reconciliation, per-record opt-out, conflict checks and safe recovery after uncertain creation. Never accept a target IP from the browser or overwrite unrelated records.
- Show required DNS/tunnel read permissions and explain that DNS does not open inbound app ports or encode VPN forwarding ports. Keep automatic record/domain discovery and allow DNS work without tunnel-read permission.

## 0.5.23

- Configure MediaVPN with the actual managed MediaSeed Compose project and bundle MediaVPN 0.1.2. Resolve app and torrent services by verified project/service labels instead of hard-coded preview container names.
- Verify named-volume ownership before stopping the source torrent client or preparing its VPN-bound replacement. Reuse existing configuration, downloads and read-only client secrets; retain the legacy standalone project default and existing VPN/port readiness checks.

## 0.5.22

- Persist GitHub metadata rate-limit cooldowns across Core restarts, keyed by credential digest without storing credentials. Keep existing shared requests, five-minute metadata caching, 15-minute main checks and configurable full-check interval.
- Preserve the last successful Core check timestamp during deferred checks. Show concise stale commit information with Core-specific guidance and translated missing-time text instead of a tunnel message or an invented timestamp.

## 0.5.21

- Pass MediaHub's configured public HTTPS origin to MediaVPN and MediaSeed browser SSO, falling back to the configured local Hub origin when no public URL exists. Preserve the private internal Hub API address and local app URLs.
- Apply browser-login origin changes to existing managed Compose apps and invalidate the preparation marker when the configured Hub domain changes. Reject credential-bearing, non-HTTPS and path/query-bearing login origins.

## 0.5.20

- Fix MediaVPN HTTPS proxy certificate access: match private TLS directory/file ownership to the actual Compose consumer, preserving existing certificate/key bytes, read-only mounts and dropped capabilities. Repair existing managed TLS binds as well as fresh installations.
- Include preparation helper changes in the app preparation fingerprint and add a public certificate/owner migration label so running TLS consumers are recreated on the user-installed update instead of retaining a failed certificate store.

## 0.5.19

- Allow MediaSeed removal when the owned MediaVPN controller is stopped and its torrent settings are verified disabled, including the never-started default with no settings file. Do not contact an inactive controller or start it as a side effect.
- Read only the fixed settings file through Docker's bounded archive API, recheck stopped state and ownership before removal, and block enabled, malformed or unverifiable settings with actionable guidance. Preserve normal controller disconnects, MediaVPN containers and app data.

## 0.5.18

- Recover failed managed app removal after container recreation by requiring fresh confirmation of the current owned installation, instead of endlessly retrying a stale container snapshot at 5%.
- Keep partial-removal retries bound to the original containers, verify ownership labels and mounts before writes, and retain preservation checks for previously recorded data volumes.

## 0.5.17

- Fix Core source updates from already installed versions: place reviewed app bundles and image runtime helper inputs under the existing `docker/` archive root. Older updaters no longer strip required Docker COPY inputs, while runtime bundle paths and media/data preservation remain unchanged.
- Verify every Core Docker COPY input survives legacy archive normalization and enforce runtime helper/source bundle parity.
- Recognize installed managed MediaSeed entries on the Seedbox home card even before an external app URL is configured; preserve actual unknown/unhealthy status and use the correct app settings ID.

## 0.5.16

- Discover Cloudflare domains, existing DNS records and remotely managed tunnels automatically after API connection, with complete bounded pagination, five-minute caching and permission-specific recovery guidance.
- Replace connected manual IP/port, zone ID and certificate-path forms with domain, record, tunnel and app selections. Resolve app origins server-side, generate new app hostnames and hide the legacy monitoring editor while connected.
- Allow explicit selection of existing remote tunnels without changing unrelated routes. Preserve conflicting DNS records, retain previous inventory during partial failures and disable publishing until discovery access is restored. Distinguish read checks from action-specific write permissions and explain shared VPN/Agent requirements.

## 0.5.15

- Include Docker Buildx in Core/Agent images and provide writable private builder configuration for automatic app/relay preparation, including the read-only host helper.

## 0.5.14

- Share one selected MediaVPN provider connection with MediaSeed and owned Plex/Jellyfin apps, including paired Linux Docker Agents. Keep private relay identities host-local, preserve web ports and block direct internet fallback for selected apps.
- Bundle reviewed first-party sources and automatically prepare app images, local HTTPS identities, integration keys and install recipes on fresh Linux installs and user-installed updates. Preserve existing data, stopped/uninstalled state and current app images when changing VPN selection; retain migration retry and Compose recovery metadata.
- Add separate Hub VPN management credentials, automatic relay dependencies and userspace WireGuard fallback for existing LXCs with TUN. Keep main fresh installations on the mediahub-platform update channel.
- Create A, AAAA and CNAME DNS records without overwriting conflicts. Install an optional cloudflared connector directly on MediaHub's Docker host and follow Plex/Jellyfin local web endpoints; VPN public IP and torrent ports do not replace HTTP routes.

## 0.5.13

- Add optional encrypted Cloudflare API access, real tunnel creation, protected connector-token downloads and app-bound DNS/ingress routes for MediaHub, MediaSeed and MediaVPN.
- Follow live local app IP/port changes with a persistent background reconciler, per-route opt-out, no-op checks, rate-limit backoff, manual conflict detection and retained unrelated routes. Keep existing monitor-only profiles available.
- Allow only explicitly published MediaHub hostnames as additional trusted browser origins; retain HTTPS, administrator, CSRF and certificate validation protections. Connector installation remains separate from remote tunnel creation.

## 0.5.12

- Verify first-party SSO with local HTTPS IP origins and optional app Settings domain overrides; no public domain is required.
- Make main the normal development repository and retain fjordcopy for explicitly requested UI experiments, with separate runtime update channels.

- Keep the footer pinned to the viewport bottom in all dock/topbar/launcher layouts, with reserved content space and a separate position for the bottom navigation dock.

- Show persisted uninstall progress for MediaSeed/MediaVPN and an activity bar for apps whose Agents do not report percentages. Preserve data checks and failure progress.

## 0.5.11

- Center the installation boxes and their headings consistently across MediaVPN, MediaSeed, Plex, container apps, Cloudflare, FjordHub and the legacy Seedbox guide.
- Show unchecked and unsupported update sources explicitly, preserve account-language updates in removal dialogs, and retain environment-specific update channels during source promotion.

- Show persisted, stage-based MediaSeed/MediaVPN installation progress, including preparation, container starts, health verification and registration. Keep progress on refresh and reach 100% only after verified completion.

- Add host-approved, administrator/HTTPS/CSRF-protected installation and reinstall flows for independent MediaSeed and MediaVPN, including persistent progress, immutable image/ownership checks, retained data and registry/SSO restoration. Route Seedbox setup to the independent app instead of the legacy dedicated-Agent installer. Host preparation remains environment-specific; never promote beta recipes or credentials into main.

## 0.5.10

- Allow Plex installation again after verified, data-preserving runtime removal. Require a matching removal receipt and absent owned containers; reuse only the matching owned tmpfs volume and restore encrypted Plex preferences instead of replacing the server identity. Preserve media and persistent app data.
- Render app removal confirmations as native modal dialogs outside app cards, preventing clipping by themed card effects and restoring keyboard focus after closing.

## 0.5.9

- Share each account's current theme, custom colors, color mode, density and motion preferences with MediaSeed and MediaVPN through SSO. Apps follow MediaHub by default and support a persistent, per-account app theme override.
- Replace first-party artwork with a coordinated monochrome MediaHub, MediaSeed and MediaVPN icon family that follows the active theme, including dynamic browser favicons.
- Style dropdown fields and their supported native pickers consistently across themes, preserving keyboard controls and native fallback.
- Move app appearance controls into an accessible Settings dialog. MediaSeed also exposes browser extension downloads and installation guidance there, keeping app headers clean.
- Preserve existing accounts, app data, credentials and media. App theme preferences use an additive table; no beta runtime data is imported. Update MediaSeed and MediaVPN from their main branches to enable the matching app features.

## 0.5.8

- Promote the tested beta workspace to release: compact app cards and Overview, five distinct themes with abstract ambient backgrounds, custom accent wheel, and independent light/dark mode.
- Keep all five account-selectable navigation layouts: sidebar, top navigation, top dock, bottom dock and compact menu. Preserve existing account preferences and default navigation.
- Include all main fixes through 68b679c: shared GitHub metadata/cooldowns, active update progress, in-app confirmations, reconnect grace, account localization and safe app installation.
- Update code in place; retain release users, secrets, app configuration, external storage mounts and media. Never import beta databases or credentials.


- Complete account-language propagation to MediaSeed and MediaVPN through hub login and subsequent session checks. Choose Danish or English when creating an administrator or managed user; ordinary users can change their own language.
- Translate remaining hub administration, FjordHub integration, setup, app-overview and error messages. MediaSeed/MediaVPN now localize dialogs, statuses, country names, tracker account/rule information, cleanup, recommendations and extension downloads. Preserve names, file paths, URLs and API values.
- MediaSeed extension 1.2.2 follows the connected account language, including saved seeding settings, import feedback and context-menu text. Preserve third-party tracker page content when injecting link capture.

- Remove the hardcoded beta badge from release navigation branding. Distinguish GitHub rate limits, rejected credentials and access restrictions in update-check errors without exposing provider response bodies.
- Fetch current approved publisher images when installing Plex, Jellyfin and the legacy Seedbox runtime, then persist immutable publisher pins. Stop on pull failure instead of silently using cached images; preserve installed versions when restarting or adopting apps. Rebuild new FjordHub installs from current upstream source with fresh base images.
- Keep MediaVPN visible before configuration and provide an honest setup page; automatic independent MediaVPN/MediaSeed deployment is still separate.
- Remove the new Proxmox bootstrap source workspace after successful installation with a resolved-path guard; stop prefetching an old Plex image during Core setup. Retain runtime images, media, app data and rollback records.

- Show official Jellyfin, Prowlarr, Radarr, Sonarr and autobrr artwork with retained licenses. Accept FjordHub's token-granted, app-specific public registry icons through the bounded local proxy without forwarding Bearer credentials to GitHub; share proxy icons on the FjordFlix dashboard and preserve safe fallbacks.

- Add Jellyfin, Prowlarr, Radarr, Sonarr and optional autobrr to the App Store with a shared HTTPS/admin/CSRF-protected container installation page. Use immutable images, operator-approved host/storage policy, reviewed plan digests, non-root containers, private LAN ports, persistent configuration, ownership-checked actions and data-preserving removal. Generate policy for new Linux installs; existing hosts need explicit operator preparation. Container state is not application health. Tracker configuration, external-client integration and the proposed automatic download queue remain separate and disabled.

- Restore strict RSS publication-date protection by default for new and existing feeds: reject old, undated, invalid, timezone-less and future-dated automatic work, including persisted queues. Add an explicit default-off per-feed discovery-only opt-in with a mass-backfill warning. Policy changes fetch a fresh baseline and clear pending work without enabling automation or replaying history. RSS dates cannot prove original tracker age; existing torrents and cleanup rules are unchanged.

- Publish each dashboard runtime observation independently so a slow Seedbox cannot delay Plex or Cloudflare. Retain last-good runtime data and Plex covers across navigation within the current signed-in session; label aged/failed observations stale rather than healthy. Share non-overlapping 10-second runtime and 60-second cover polling, pause hidden-page requests, abort abandoned work and clear private cached data on authentication transitions and app deletion. Existing settings, dashboard layout and FjordFlix polling remain unchanged.

- Expand the existing FjordHub integration with keyed app-info/permissions, validated installed LAN ports, revision-refreshed protected icon proxying and explicit administrator/CSRF update controls for FjordHub and child apps. Poll statuses sequentially every 45 seconds (5 while running), retain stale in-progress state through restart/timeouts, treat HTTP 202 only as acceptance, and never add remote updates to the automatic global queue. Preserve older resource responses and local launch overrides; use safe icon fallbacks for non-origin artwork.

- Add a configurable Active uploads dashboard card for torrents currently sending data to peers, with count, combined upload speed and the five busiest torrents. Reuse the shared dashboard snapshot, exclude stopped/paused and zero-speed seeds, distinguish unavailable data from zero activity, and retain existing saved layout preferences. Available in Choose cards and Settings; new dashboard defaults place it next to ongoing torrents.

- Keep dashboard card geometry identical when entering and leaving layout editing: original and saved layouts now use the same engine in both modes. Draw both ends of the actual CSS tracks (including gaps) in the edit grid, and keep Choose cards registration/order stable while visibility or asynchronous content changes.

- Add authenticated per-integration FjordHub home pages with internal sidebar navigation, an explicit external Open FjordHub action, Docker/app/FjordFlix overview and administrator-only local app launch URL settings. Persist same-host, explicit-port overrides with session/CSRF checks and consistent sidebar/card/dashboard links; clearing restores API/management fallback, and removal cleans up scoped settings. Bundle verified MIT Fjord3D artwork with its copyright/license; use clearly documented ordinary interface-icon fallbacks where official artwork has no verified redistribution license, rather than copying screenshots or inventing replacement logos.

- Reduce Cloudflare Tunnel release-check requests with shared, restart-persistent validated metadata, ETag revalidation and existing encrypted GitHub access. Persist GitHub cooldowns even for manual/forced checks; show deferred checks and explicitly stale versions without marking a working tunnel unhealthy or hiding genuine source failures. Tunnel updates remain manual.

- Add a dedicated configurable Plex-style FjordFlix dashboard card under Your apps, including ordered last-10 protected poster carousel, library/active-stream counts and independent stale/empty/error states. Share one child-app link resolver between navigation, app cards and dashboard: preserve validated explicit app addresses/nondefault ports, reject unsafe or untrusted destinations, and explicitly label FjordHub management links when the resource API omits app addresses (never guess ports).

- Add confirmed, administrator-only permanent removal for disconnected FjordHub integration entries. Remove only the selected local record, token and cached snapshots/gallery; never uninstall or modify FjordHub. Fence late refresh/discovery, persist discovery opt-outs across restarts, and explain environment-managed entries that require operator configuration changes first. Existing disconnect still preserves the row.

- Show qBittorrent's reported popularity as a sortable torrent-list column on desktop and mobile. Preserve saved sort preferences, display real zero values with two localized decimals, and show unavailable/invalid values as unknown without calculating a replacement.

- Extend the read-only FjordHub resources integration with optional FjordFlix appdata: the last 10 recently added titles in API order, current streams and playback metadata, independently stale app/resource snapshots, and authenticated bounded same-origin poster proxying. Add backend-only `FJORDHUB_BASE_URL` / `FJORDHUB_ACCESS_TOKEN` configuration and sequential 10-second polling; old responses without appdata remain compatible.

- Verify identical qBittorrent username/password reapplication with a fresh login instead of rejecting it; allow username-only changes while still proving the previous login is rejected. Report sanitized rotation preflight errors and correlate status with the current operation, so an older healthy VPN journal cannot mask a failed client change. Interrupted/partial rotations still require operator recovery; no live rotation or deployment performed.

- Report asynchronous Seedbox credential rotation separately from installation health, including a sanitized failed step and interrupted-operation recovery state. Poll the result in **Use my MediaHub login** so an accepted request cannot hide a later failure; keep encrypted recovery references private. No live password changes or deployment are performed.

- Add opt-in **Use my MediaHub login** to Seedbox installation and existing Seedbox Settings. Reauthenticate the administrator's entered password and enabled MFA with session/CSRF checks; copy the server-side account username through existing encrypted credential import/client rotation without changing VPN or WebUI protections. Clearly reject logins incompatible with Seedbox's existing policy and explain one-time copying, not continuous password synchronization. Existing users must opt in after updating; no live rotation or deployment is automatic.

- Add regression checks confirming fast/full MediaHub platform updates target only Core/Agent, use dependency-isolated starts, and leave managed Plex/VPN running during Agent shutdown. Document the difference between platform updates and Plex/VPN updates or safety failures.

- Add a dedicated qBittorrent WebUI control under Seedbox Settings, including an explicit unconfigured state and Danish access guidance. Document opt-in authorized client SSH tunneling to the reviewed loopback WebUI port and Core operator-link configuration; preserve qBittorrent login, CSRF/host validation and VPN fail-closed behavior. No endpoint is exposed or live deployment performed.

- Make every automatic RSS feed use newly discovered entry IDs regardless of publication date, including older torrents exposed by rotating feeds and undated/future-dated entries. Preserve creation/activation baselines, durable retries and the 20-item per-poll limit. Previously seen IDs, including entries skipped by the former date rule, are not automatically replayed; manual selection remains available.

- Add an explicit `--refresh-helper` migration for the privileged host updater while preserving existing source trust or image-only update policy. Explain that updating Core alone does not enable host cleanup, and publish capabilities only after replacing the real helper.
- Keep maintenance app-health counts consistent with the badge: unknown reports are not counted as healthy, and an empty installation list is explicitly unknown. Disable cleanup submission while its status is unavailable or still loading.

- Show qBittorrent's accumulated seeding time directly below each torrent name on desktop and mobile, including zero and unavailable values; keep the existing seeding-time sort and expanded details.

- Load App Store installation badges and setup selections from lightweight installed-app metadata (`GET /apps?include_health=false`) without waiting for remote health checks. The default app listing still includes health, and store controls still wait for installation and integration metadata.

- Reuse app and integration snapshots across authenticated pages instead of repeating page-mount requests and integration polls. Cancel obsolete reads/retries, pause integration polling in hidden tabs, and batch app health event bursts into a bounded refresh.
- Load optional pages and the upload client on demand, and fetch authentication/setup state in parallel. Reduce initial JavaScript from 948.42 kB to 767.32 kB (gzip 284.11 kB to 235.75 kB) in the local production build.
- Check independent app health reports concurrently (up to eight at a time) for the app list and initial live stream, retaining response order, authentication, bounded remote timeouts and status validation. Fetch installed app rows with one database query instead of one additional query per app.

- Use the MediaHub logo for iPhone and Android home-screen webapps with an Apple touch icon, maskable PNG icons and a standalone web app manifest.

- Follow the configured GitHub repository's main branch by commit instead of requiring a new release or version number. Pin source downloads to the selected commit and retain bounded archive validation, builds, snapshots and rollback.
- Display installed and available commit IDs, and add a one-time host-helper migration for same-version source updates.

- Serialize release publishing by target tag so overlapping runs cannot collide while uploading the same release assets.

## 0.4.29 - 2026-09-30

- Release merged PR #1: cancel superseded folder requests so delayed responses cannot replace the current folder; retain loaded data on failed refreshes of the same path.
- Report aggregate update-check errors as incomplete checks while keeping successfully discovered updates visible. Clear old notices before checking again.
- Add browser regression coverage for folder navigation and incomplete update checks, and correct the disconnected-progress accessibility assertion.

## 0.4.28 - 2026-09-30

- Preserve the Agent's supplementary private-state group 10001 alongside primary media group 1000. An explicit Docker USER group in v0.4.26 discarded membership needed to read host storage evidence and blocked Plex recovery.
- Explicitly retain Plex VPN's outbound bridge when attaching the internal control network. Reconnect a missing bridge on an owned, stopped VPN before its normal verified start; do not change a running VPN's networks.
- Extend image CI checks to require both primary media and supplementary private-state groups.

## 0.4.27 - 2026-09-30

- Label update progress and steps as last received while Core is unreachable, and show a separate reconnecting indicator instead of animating a stale build step.
- Explain the possible service-restart pause without claiming the unseen server state; restore live progress when status polling succeeds.

## 0.4.26 - 2026-09-30

- Run the Agent image with UID 10001 and primary media GID 1000 so mergerfs writes do not depend on resolving Docker supplementary groups.
- Preserve Agent state ownership and existing media permissions. The normal image update applies the new identity to installations without a Compose user override.
- Verify the built production Agent image's effective UID and GID in CI.

## 0.4.25 - 2026-09-29

- Preserve Agent filesystem and path-policy errors through Core, including HTTP 403 responses for denied writes, read-only storage and disabled directory creation.
- Distinguish authentication failures from storage failures for folder preparation and streamed upload chunks; handle malformed rejection responses without exposing proxy pages.

## 0.4.24 - 2026-09-29

- Recommend and prefill 4 CPU cores and 10240 MiB RAM for new FjordHub LXCs.
- Run the reviewed FjordHub installer from the guide over fingerprint-pinned root SSH, with a live console and durable installation status.
- Share the command template between browser preview and backend execution; accept validated configuration only, never browser-supplied shell commands.
- Keep SSH passwords in job memory only, redact bounded logs, prevent duplicate/racing jobs and require target inspection after failed or interrupted attempts.

## 0.4.23 - 2026-09-29

- Align FjordHub guide inputs at the top of each form row so Timezone does not stretch or shift downward when adjacent fields have helper text.

## 0.4.22 - 2026-09-29

- Fix Linux folder creation and resumable uploads through search-only ancestor directories by using O_PATH with O_DIRECTORY/O_NOFOLLOW instead of requiring read permission on every ancestor.
- Report the actual filesystem error, affected path and Agent identity for permission failures; distinguish read-only mounts, full disks, quotas and path limits.
- Show folder preparation errors above the upload queue and avoid repeating the same failed folder-creation request for every file.

## 0.4.21 - 2026-09-29

- Generate copyable/downloadable FjordHub setup commands for a new unprivileged Debian 13 Proxmox LXC or an existing Debian host.
- Configure container ID, storage, separate data disk, CPU/RAM, bridge, DHCP/static IPv4, application paths, port and timezone from the guide.
- Generate a private session secret on the target and write the selected `.env` values automatically. Refuse occupied IDs and existing installations; never run provisioning from MediaHub.

## 0.4.20 - 2026-09-29

- Preserve actual update steps, progress and console history across temporary connection failures instead of replacing them with a fixed 82% fallback that omits Build.
- Add an expandable Console to platform update progress, with bounded live history and automatic scrolling that pauses when reading older lines. Keep the result visible after completion.
- Stream bounded, redacted Docker build output from the host helper. Existing helpers retain status-message history; detailed build output requires a one-time helper refresh from this checkout.

## 0.4.19 - 2026-09-29

- Accept files and whole folders dropped directly onto the existing Media files panel, preserving nested paths and mixed selections.
- Keep the Upload menu's Files and Folder choices, existing 5 MiB tus transfers and Stop controls.
- Highlight the drop target, block overlapping uploads and prevent accidental file navigation. Read all directory batches and report unreadable or oversized selections before uploading.

## 0.4.18 - 2026-09-29

- Reuse the frontend build across backend-only releases: read the displayed version from Core and exclude package release metadata from Docker build inputs.
- Run Python application source directly with locked dependencies, eliminating repeated package/build-tool installation for source edits.
- Skip building, stopping, snapshotting and recreating an unchanged local Agent. Bind reuse to a root-owned source fingerprint and the installed immutable image; rebuild if evidence is missing or invalid.
- Preserve Core backup and rollback while an unchanged Agent continues running. The first update establishes the Agent fingerprint.
- Existing hosts must refresh the root-owned updater once using `scripts/enable_source_updates.py` from this version's checkout to enable Agent reuse. Normal Core updates do not replace that helper. Dockerfile improvements work with the existing source updater.

## 0.4.17 - 2026-09-29

- Replace the two storage upload buttons with one Upload button offering Files or Folder.
- Preserve tus transfers, folder structure and Stop controls.

## 0.4.16 - 2026-09-29

- Cache Python dependencies before copying application source, reusing the same dependency layer between Core and Agent builds.
- Fetch frontend packages from the lockfile before copying the versioned package manifest; install offline so version-only releases do not repeat package downloads.
- Preserve the existing verified-source, backup, preflight and rollback update workflow. The first build warms the new cache; later builds benefit while dependencies and the base image remain unchanged.

## 0.4.15 - 2026-09-29

- Use tus-js-client for browser uploads with 5 MiB chunks and automatic offset recovery.
- Add authenticated tus HEAD/PATCH endpoints while preserving folder uploads, Stop controls and no-overwrite publication.

## 0.4.14 - 2026-09-29

- Upload a whole folder from Storage, preserving its name and nested files.
- Add Stop beside each file's progress and Stop all for the upload queue.
- Transfer large files in bounded 8 MiB chunks with persisted offsets and recovery from lost acknowledgements.
- Serialize cancellation with in-flight writes, remove unfinished temporary files, and preserve completed media and existing files.
- Clean abandoned sessions after 24 hours and warn before leaving an active upload page.
- Cover nested folder uploads, chunk retries, active/queued cancellation and responsive controls in browser tests.

## 0.4.13 - 2026-09-29

- Show only approved media roots in the torrent destination selector; existing movie-title folders no longer appear.
- Display the configured media names without the MediaHub or Top folder decoration.
- Reject obsolete child-folder destination IDs when adding torrents, while preserving actions on existing jobs.
- Keep media content, mount paths, VPN settings and torrent state unchanged.

## 0.4.12 - 2026-09-28

- Preserve readable source permissions inside non-root Docker images, including builds run under a private systemd umask.
- Add POSIX permission regression coverage and run source-built images as their non-root runtime user in CI.
- Run isolated non-root image smoke checks on the host before stopping any existing service.
- Preserve uid/gid in configuration backups and restoration for non-root Core/Agent runtimes.
- Supersede 0.4.11; its first live deployment failed startup checks and required ownership repair during rollback.

## 0.4.11 - 2026-09-28

- Build platform updates from verified GitHub source on the server, before stopping Core.
- Preserve configuration backup and rollback; never include media in the update transaction.
- Add source-build progress and explicit host capability/trusted repository checks.
- Provide a one-time migration helper for existing installations; keep image bundles optional for older clients.

## 0.4.10 - 2026-09-28

- Supersede the v0.4.9 storage-destination release with the repository's
  canonical Python formatting so the full GitHub CI gate passes unchanged.

## 0.4.9 - 2026-09-28

- Allow Seedbox administrators to choose among explicitly approved writable
  logical destinations such as Downloads, Movies, TV Shows and Other when
  adding a torrent.
- Keep destination selection fail-closed: the browser receives opaque IDs,
  read-only or merely mounted storage is excluded, and the Agent revalidates
  the selected root or direct child folder before contacting qBittorrent.
- Keep torrent actions available for jobs stored in any approved writable
  destination while preserving compatibility with the original Downloads root.

## 0.4.8 - 2026-09-28

- Keep sidebar app-health indicators synchronized with the same remote status
  used by app detail pages through SSE-triggered, focus-triggered and bounded
  visible-page refreshes.
- Move Seedbox block-device and mount inventory out of the daily app view into
  a collapsed troubleshooting section under Settings → Maintenance.
- Let administrators select the Downloads top folder or an existing direct
  child folder when adding a torrent. Destination identifiers are opaque and
  are revalidated by the Agent; arbitrary paths, hidden folders and symlinks
  remain unavailable.

## 0.4.7 - 2026-09-25

- Add a dedicated App Store navigation entry with stable, equal-height catalog
  cards and loading placeholders that prevent content from moving while data
  arrives.
- Keep a fresh installation's Apps page limited to actually installed apps;
  Cloudflare Tunnel moves from the installed list into its guided App Store
  flow until the administrator saves a configuration.
- Add a complete Cloudflare setup and edit flow for multiple tunnels, public
  routes, private HTTPS origins, internal CA validation and optional connector
  metrics without requesting an account-wide Cloudflare token.
- Add FjordHub to the App Store with a guided deployment from its official
  GitHub source and a separate least-privilege, read-only Access Token
  integration step.
- Add a one-time navigation migration so existing installations receive the
  App Store entry without overriding later user customisation.

## 0.4.6 - 2026-09-25

- Turn the completed update check into a clear green "Everything is up to date" state.
- Keep multiple Cloudflare tunnel monitoring profiles and show edit, remove, and add controls after installation.
- Reserve the assisted Cloudflare wizard for first-time setup and explicit configuration changes.
- Add a direct Plex server settings button and clear stale app-specific update results when switching apps.
- Extend Cloudflare monitoring to aggregate routes from saved tunnel profiles without storing Cloudflare account tokens.

## 0.4.5 - 2026-09-25

- Fixed platform updates failing before download when the private staging
  directory had been created by root. Fresh installs now create the directory
  for the unprivileged Core user, the host updater verifies that ownership, and
  Core reports a clear storage-permission error instead of a generic failure.

## 0.4.4 - 2026-09-25

- Added an assisted, least-privilege Cloudflare Tunnel monitoring setup that
  distinguishes one tunnel from its published routes and redundant connector
  sessions. It supports route-only checks or private Prometheus metrics without
  receiving an account API token or tunnel token.
- Made app submenu selection fill the sidebar row and aligned update cards with
  consistent rows, actions, messages and expandable advanced settings.
- Successful update checks with no available releases now automatically resolve
  stale update notifications while preserving their activity audit entries.

## 0.4.3 - 2026-09-25

- Fixed the Plex remote-reachability status check when the Agent correctly runs
  on an internal-only control network. The check now uses a short-lived,
  secretless, read-only bridge helper with no mounts or capabilities, while the
  Agent itself remains isolated.

## 0.4.2 - 2026-09-25

- Fixed Plex remote access through Proton NAT-PMP. Proton translates the
  allocated public port to the private port requested by MediaHub; the
  fail-closed `tun0` redirect now matches that translated private port before
  forwarding traffic to Plex. Added a regression test for the exact rule.

## 0.4.1 - 2026-09-25

- Fixed offline Core/Agent image activation after discovering that Docker
  correctly verifies and loads a digest-exported bundle but does not preserve
  the registry digest as a locally addressable image reference. The
  networkless host updater now binds the single loaded image ID to a local tag
  derived from the release version and verified bundle hash, enforces
  `pull_policy: never`, and still rejects untrusted release repositories.

## 0.4.0 - 2026-09-25

- Added compact update cards whose progress stays inside the app being checked
  or updated, preventing layout jumps and hidden status at the top of the page.
- Added configurable scheduled update checks, deduplicated notifications, live
  SSE refresh and an available-update badge in the sidebar.
- Added a complete, rollback-protected MediaHub Core and local Agent updater for
  digest-verified private GitHub Release bundles. The networkless root helper
  enforces trusted image repositories, stable forward-only versions, bounded
  configuration snapshots, health verification and automatic rollback; media is
  outside the transaction.
- Cloudflare Tunnel is now always visible as an optional app. Without a local
  helper it explains that monitoring is not configured; with one it reports
  connections, route health and official cloudflared release information.

## 0.3.0 - 2026-09-25

- Added reusable operation progress with stages, completion percentage and
  redacted technical details for Maintenance and update actions.
- Added a safe Maintenance workspace under Settings with live Core, Agent,
  storage and app checks, explicit movie/TV protection and direct links to
  storage, updates and backups.
- Storage browser folder-size totals and streamed, administrator-only uploads that
  stay inside approved media roots and never overwrite existing files.
- Added encrypted, repository-scoped GitHub access for private release discovery.

- Stable app-card loading with reserved layout space and direct app shortcuts in the sidebar.
- Simple-first dashboard with media storage first and collapsed Core/app diagnostics.
- Main-volume storage summary with technical mappings and read-only archives behind disclosures.
- Configurable public GitHub release discovery requiring a SHA-256 identified release manifest.
- GHCR release workflow with immutable image digests and build attestations; host installation
  remains gated until the transactional updater and rollback path are deployed.
- Added dedicated fail-closed Proton WireGuard networking for Plex remote access,
  renewable NAT-PMP port forwarding and actual public-port reachability checks.
- Added Cloudflare Tunnel health and official release monitoring plus a guided,
  provider-safe App Store setup foundation for a future installer.

## 0.2.0

- Real Plex installation, read-only media libraries, streams/resources and image update/rollback.
- Optional isolated Proton Seedbox with verified VPN, fail-closed recovery and NAT-PMP.
- Daily torrent management, force recheck and remove-job-without-data-deletion.
- TOTP enrollment/recovery, secure direct HTTPS, protected runtime secrets and memory limits.
- Encrypted Core/Plex/Seedbox configuration backups and offline non-overwriting restore.
- Logical shared storage, disk identity checks, missing-storage guards and live resource health.
- Refreshed simple-first navigation, version/maintenance page and guided app selection.
- New-install Linux bootstrap and public documentation without private deployment reports.
- FjordHub Access Token adapter using the actual read-only integration API.
- Limitations: Core/Seedbox updates and certificate renewal remain operator-managed;
  remote Seedbox host preparation is not an automatic Proxmox provisioning service.

## 0.1.0-dev

- Separate Phase 1 Core foundation: API, local auth, SQLite migrations and live dashboard.
- Generic manifests and a database-only mock adapter.
- Read-only storage validation, activity and settings.
- Proxy-free local HTTP serving and an isolated development Compose definition.
- Unit, integration and real-browser tests. Not a production release.
