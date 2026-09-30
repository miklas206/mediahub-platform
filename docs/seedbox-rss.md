# Private RSS torrent selection

Open **Apps → Seedbox → RSS torrents**. Paste the complete private HTTPS RSS
address from your tracker, including its RSS key, then choose **Save and load
feed**. A key alone does not identify the tracker or its feed endpoint.

Search the titles, select up to 20 entries, choose an approved download location,
and click **Add selected**. New torrents are stopped by default. Enable **Start
selected torrents immediately after safety checks** to start them, or use Resume
in the torrent list afterwards. Existing torrent hashes are not added again.
Failures are reported per item and remain selected for retry.

Use **Refresh feed** to fetch recent entries. Up to 200 entries are displayed.
There are no automatic download rules. **Remove feed** deletes the saved feed and
its cached entries; torrents already added to Seedbox are retained.

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

This feature needs an updated Core/frontend. It reuses the existing Agent torrent
add API, so it does not introduce an Agent RSS service or require an Agent update.
