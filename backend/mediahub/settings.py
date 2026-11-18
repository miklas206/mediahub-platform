import os
import re

from sqlalchemy import select

from mediahub.contracts import PlatformSettings, UserPreferences
from mediahub.db import Setting, User


def installation_language(db):
    key = "installation.language"
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        locale = next(
            (
                os.environ[k]
                for k in ("MEDIAHUB_HOST_LOCALE", "LC_ALL", "LC_MESSAGES", "LANG")
                if os.environ.get(k)
            ),
            "",
        )
        language = "da" if re.split(r"[-_.@]", locale.lower())[0] == "da" else "en"
        row = Setting(key=key, value={"language": language})
        db.add(row)
        db.flush()
    return row.value["language"]


class SettingsService:
    def __init__(self, sessions):
        self.sessions = sessions
        with sessions.begin() as db:
            self.default_language = installation_language(db)
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

    def user_preferences(self, user_id: str) -> UserPreferences:
        with self.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == f"user.preferences:{user_id}"))
            user = db.get(User, user_id)
            return UserPreferences.model_validate(
                {
                    **(row.value if row else {}),
                    "language": user.preferred_language if user else "en",
                }
            )

    def save_user_preferences(self, user_id: str, preferences: UserPreferences):
        with self.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == f"user.preferences:{user_id}"))
            # Each preferences panel submits its own fields. Defaults from an omitted
            # panel must not replace that account's existing choices.
            user = db.get(User, user_id)
            saved = UserPreferences.model_validate(
                {
                    **(row.value if row else {}),
                    "language": user.preferred_language,
                    **preferences.model_dump(exclude_unset=True),
                }
            )
            user.preferred_language = saved.language
            if row:
                row.value = saved.model_dump()
            else:
                db.add(Setting(key=f"user.preferences:{user_id}", value=saved.model_dump()))
        return saved
