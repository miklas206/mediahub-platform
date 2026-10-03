# Optional automatic torrent cleanup

Cleanup is **off by default**. Use **Never — keep torrent and files** to keep
seeding indefinitely without automatic removal. Saving this choice for an
existing torrent saves an explicit individual override that prevents automatic
cleanup, including cleanup originally configured by its RSS feed.

The same controls are available when adding a torrent file or magnet, in RSS
feed settings, and through the settings icon beside an existing torrent. The
dialog edits only that torrent; saving never changes its feed or other torrents.
An **Individual rule** label identifies a saved per-torrent override, including
**Never**. RSS rules
are copied to future torrents as they are added (including manual feed
selections). Changing a feed does not silently alter existing torrent rules;
edit those individually. Removing/disabling a feed does not cancel its torrents'
existing cleanup rules. Already-present duplicate torrents are never reconfigured
by an RSS retry or another add request.

Choose one trigger:

- Seeding time: a chosen whole number of hours from 1 to 8760.
- Uploaded amount: a chosen ratio from 0.1 to 100 relative to content size.
- Both time and ratio: both thresholds must be reached.
- Either time or ratio: the first threshold reached is sufficient.

Ratio is uploaded bytes divided by the torrent's content size. For 100 MB,
ratio 2.0 requires 200 MB uploaded, even if the file was imported/rechecked and
the torrent client reports no downloaded bytes. Time uses qBittorrent's reported
accumulated seeding seconds. The download must be complete before any cleanup.
Existing torrents use their existing uploaded bytes and seeding time; saving
a rule already fulfilled can trigger cleanup on the next check.

Choose the action separately:

- **Remove torrent job — KEEP files**: stops seeding by removing the job; files
  remain available to Plex and other applications.
- **Remove torrent job AND DELETE files**: permanently deletes that torrent's
  downloaded files, including content in Plex's library. The UI shows this
  consequence beside the selector.

The Seedbox Agent checks rules every minute, including when Core or the browser
is closed. Its persistent metadata ties each rule to the torrent hash, creation
time, save path and a unique job tag. Removed/replaced/moved jobs cannot silently
inherit an old rule. Only approved storage is eligible. File deletion checks the
file paths and other jobs for overlaps; symlinks, ambiguous metadata, unapproved
paths or shared files block deletion. A blocked/waiting message is shown in the
torrent list. The ordinary **Remove job** button still always keeps files.

Deployment requires **both updated Core/frontend and the separate Seedbox
Agent**. An older Agent advertises no cleanup capability: controls remain
disabled, and enabling an RSS cleanup rule is rejected instead of silently
ignoring it. Existing installations and rules are never enabled automatically.
