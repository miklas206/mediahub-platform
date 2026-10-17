# Plex and Jellyfin connectivity

The Plex supervisor automatically publishes the approved installation LAN IPv4
address as a secure `plex.direct` URL using Plex's current CertificateUUID. This
applies to new installations and upgrades of existing installations, including
ones where the URL was added manually. Other custom URLs remain intact. A later
address or certificate change replaces only the previously managed URL. Changes
are verified through Plex, checkpointed in the encrypted preference vault and
republished to Plex discovery. Failed publication remains retryable. Removal
clears the ownership receipt. Authentication exceptions are never added.

This fixes discovery of a Docker-hosted server whose advertised container IP is
unreachable from LAN devices. It does not change Plex's network classification.
With bridge/VPN networking, Plex may still regard a direct LAN client as remote;
the optional LAN Networks setting requires Plex Pass and is not exposed by every
account. DNS rebinding protection can also block private `plex.direct` names.
Check the actual session's address, `local` and `relayed` values before declaring
local playback verified. Remote reachability uses the independent verified
Proton port lease; the LAN URL does not replace it. Since 0.6.45 the verified
public endpoint is also published as an explicit HTTPS discovery URL, because
Plex's detected outbound IP can differ from the public forwarding namespace.
IP/port rotations replace only the previous managed public URL. Disabling
forwarding removes that URL while preserving LAN and user-configured addresses.

Jellyfin now exposes the same managed domain editor as Plex. The administrator
first configures Cloudflare and enables the shared MediaVPN web gateway, then
chooses a domain on the installed Jellyfin page. The backend only accepts an
installed, non-mock Plex or Jellyfin instance, preserves other app routes and
uses the existing DNS ownership, TLS validation, reconnect and cleanup flow.
Upgrades expose this editor without resetting the saved gateway or enabling
previously disabled domains automatically. It requires a selected domain;
installing this version alone does not publish Jellyfin.

## Playback verification

Remote access and codec support are separate checks. Compare the same media,
audio track, client and output chain. Record the Jellyfin client version,
playback method and transcode reasons. Video transcoding from HEVC to H.264 can
reduce 4K/HDR to 1080p/SDR. Transcoding TrueHD Atmos to AAC does not retain the
original Atmos bitstream. Do not disable transcoding globally or declare codecs
supported by a client without checking actual playback.

A GPU device mapping alone does not select Jellyfin hardware acceleration.
Check Dashboard / Playback / Transcoding against the granted GPU. Existing
Jellyfin preferences remain owned by the administrator. `libx264` in a playback
log means software video encoding, whereas `h264_nvenc` indicates NVIDIA
encoding. Test the actual Xbox and soundbar for 4K/HDR and Atmos output; server
configuration and automated tests alone cannot prove that output.
