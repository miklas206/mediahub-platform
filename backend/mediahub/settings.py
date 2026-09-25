from sqlalchemy import select

from mediahub.contracts import PlatformSettings
from mediahub.db import Setting


class SettingsService:
    def __init__(self, sessions):
        self.sessions = sessions
        self._add_store_navigation_once()

    def _add_store_navigation_once(self):
        """Add the new App Store once without overriding later user choices."""

        marker_key = "navigation.app-store.v1"
        with self.sessions.begin() as db:
            marker = db.scalar(select(Setting).where(Setting.key == marker_key))
            if marker:
                return
            row = db.scalar(select(Setting).where(Setting.key == "platform"))
            if row:
                value = dict(row.value)
                navigation = list(value.get("visible_navigation") or [])
                if "/store" not in navigation:
                    try:
                        position = navigation.index("/apps") + 1
                    except ValueError:
                        position = 1
                    navigation.insert(position, "/store")
                    value["visible_navigation"] = navigation
                    row.value = value
            db.add(Setting(key=marker_key, value={"applied": True}))

    def get(self) -> PlatformSettings:
        with self.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == "platform"))
            return PlatformSettings.model_validate(row.value) if row else PlatformSettings()

    def save(self, settings: PlatformSettings):
        with self.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == "platform"))
            if row:
                row.value = settings.model_dump()
            else:
                db.add(Setting(key="platform", value=settings.model_dump()))
        return settings
