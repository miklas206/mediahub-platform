from sqlalchemy import select

from mediahub.contracts import PlatformSettings
from mediahub.db import Setting


class SettingsService:
    def __init__(self, sessions):
        self.sessions = sessions

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
