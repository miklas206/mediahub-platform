"""Allow every running completed torrent to seed without upload queue limits."""

import json

SEEDING_LIMITS = {"max_active_uploads": -1, "max_active_torrents": -1}


async def ensure_seeding_limits(client, preferences):
    if all(preferences.get(key) == value for key, value in SEEDING_LIMITS.items()):
        return
    response = await client.post(
        "/api/v2/app/setPreferences", data={"json": json.dumps(SEEDING_LIMITS)}
    )
    response.raise_for_status()
    response = await client.get("/api/v2/app/preferences")
    response.raise_for_status()
    verified = response.json()
    if any(verified.get(key) != value for key, value in SEEDING_LIMITS.items()):
        raise ValueError("Unlimited active seeding could not be verified")
