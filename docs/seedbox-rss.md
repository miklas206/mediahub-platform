# Private RSS torrent selection

Open **Apps → Seedbox → RSS feeds**. Add a name, the complete private HTTPS RSS
address from your tracker (including its RSS key), and an approved destination.
Up to 20 independent feeds are supported. A key alone does not identify the
tracker or its feed endpoint.

Enable **Automatically download new entries** if wanted, then choose **Add feed
and skip existing entries**. Saving first reads the complete supported feed and
persists all current entry IDs as a baseline. None of these entries are submitted
automatically. If that first fetch fails, no feed is created and nothing starts.

Automatic downloads also require a timezone-qualified publication date newer
than the saved activation time and no later than the current check. Old entries
are skipped even when their IDs change or the tracker later exposes older pages.
Missing, invalid or timezone-less dates require manual selection. Existing feeds
without a saved activation time establish a fresh baseline on their next check
and discard their old pending queue, rather than replaying uncertain history.

Core checks automatic feeds every five minutes, even with the browser closed.
Newly discovered entries are persisted in a queue before being added through the
existing VPN-protected Agent API, with immediate start after safety checks.
Processed IDs and pending entries survive Core restarts. A retry after an
uncertain response uses the Agent's existing infohash duplicate check. Torrents
already present are not restarted or moved to another feed's destination.

Each feed displays its automatic/manual state, saved destination, last check,
pending count and failure message. **Check feed now** runs the same discovery
and automatic-download process immediately. Failures preserve the queue and
history for retry. Up to 20 pending items per feed are processed per pass.

Under **Feed settings**, change the destination or turn automation on/off.
Enabling it establishes a fresh baseline: current entries, including ones added
while automation was off, are skipped. Disabling clears pending automatic work;
torrents already handed to Seedbox continue running. Changing a destination
affects subsequent submissions, not torrents already installed.

An existing single-feed configuration migrates as manual-only. Choose its
destination before enabling automation. Migration never activates downloads.

Expand **Browse and select entries manually**, search the titles, select up to 20
entries, and click **Add selected** to use that feed's saved destination. New
manual torrents are stopped by default. Enable **Start manually selected torrents
immediately** to start them, or use Resume
in the torrent list afterwards. Existing torrent hashes are not added again.
Failures are reported per item and remain selected for retry.

Up to 200 entries per feed are displayed; the initial baseline includes all
entries parsed, up to 5000 within the response size limit. Larger feeds are rejected
instead of silently establishing a partial baseline. A tracker can only expose
its current feed window: entries that appear and disappear between checks cannot
be discovered. GUID/Atom IDs are preferred for stable identity; otherwise the
download URL is used. Feeds whose IDs change on every request are unsuitable for
automatic downloading.

**Remove feed** deletes its configuration, history and pending queue; torrents
already added to Seedbox are retained. History is never silently pruned: a feed
with 100000 recorded IDs or over 1000 pending entries reports an error rather
than losing history and risking a backlog download.

The feed address and cached download links are encrypted with Core's existing
installation key. The API returns titles, publication text and opaque item IDs;
it does not return the private feed/download addresses. Configuration backups
retain the encrypted setting and must retain the matching installation key.

Feed and `.torrent` metadata requests originate from **MediaHub Core**, not the
Seedbox VPN. Actual torrent transfers use the existing VPN-protected Agent flow,
including its approved storage and safety checks. A tracker must permit Core's
network address to access its feed. Cookie/login-page scraping is not supported.

Only public HTTPS endpoints on port 443 are accepted. TLS verification remains
enabled; DNS results and redirects are checked and the connection is pinned to a
validated public address. Responses are limited to 2 MiB. RSS and Atom enclosures
are preferred; magnet links and direct torrent links are supported. An HTML
details page cannot be used as a torrent file.

RSS discovery needs an updated Core/frontend and reuses the Agent torrent add API.
Optional [automatic torrent cleanup](torrent-cleanup.md) additionally needs an
updated Seedbox Agent. Each feed's cleanup rule applies to newly added torrents;
the default keeps both jobs and files indefinitely.
