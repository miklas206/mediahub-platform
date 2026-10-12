import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select

from mediahub.db import Session, Setting, User, UserSecurity
from mediahub.errors import DomainError
from mediahub.mfa import MFAService

hasher = PasswordHasher()
# Runtime-generated dummy hash equalizes the expensive path for unknown usernames.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = "mediahub_session"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, sessions, config, events):
        self.sessions = sessions
        self.config = config
        self.events = events
        self.attempts: dict[str, list[float]] = {}
        self.mfa = MFAService(config)

    def needs_setup(self) -> bool:
        with self.sessions() as db:
            return db.scalar(select(User.id).limit(1)) is None

    def create_admin(self, username: str, password: str):
        username = username.strip().lower()
        if not username or len(username) > 80 or len(password) < 12 or len(password) > 256:
            raise DomainError(
                "invalid_credentials", "Use a username and a 12–256 character password"
            )
        with self.sessions.begin() as db:
            if db.scalar(select(User.id).limit(1)):
                raise DomainError("already_initialized", "An administrator already exists", 409)
            db.add(User(username=username, password_hash=hasher.hash(password)))

    def users(self):
        with self.sessions() as db:
            return [{**self.public_user(user), "appRoles": self.app_roles(db, user.id)} for user in db.scalars(select(User).order_by(User.username))]

    @staticmethod
    def app_roles(db, user_id):
        row = db.scalar(select(Setting).where(Setting.key == "app_roles:" + user_id))
        return dict(row.value) if row else {}

    def app_role(self, user_id, package_id):
        with self.sessions() as db:
            user = db.get(User, user_id)
            if user is None:
                raise DomainError("unauthorized", "User no longer exists", 401)
            roles = self.app_roles(db, user_id)
            role = roles.get(package_id, "administrator" if user.role == "administrator" else None)
            if role not in {"administrator", "user", "viewer"}:
                raise DomainError("app_access_denied", "You do not have access to this app", 403)
            return role

    @staticmethod
    def public_user(user):
        return {"id": user.id, "username": user.username, "role": user.role, "createdAt": user.created_at}

    def save_user(self, username, password, user_id=None, role=None, app_roles=None):
        username = username.strip().lower()
        if not username or len(username) > 80 or (password and not 12 <= len(password) <= 256) or (not user_id and not password):
            raise DomainError("invalid_credentials", "Use a username and a 12-256 character password")
        with self.sessions.begin() as db:
            user = db.get(User, user_id) if user_id else None
            if user_id and user is None:
                raise DomainError("user_not_found", "User not found", 404)
            target_role = role or (user.role if user else "user")
            if target_role not in {"administrator", "user"}:
                raise DomainError("invalid_role", "Invalid hub role")
            if app_roles is not None and any(key != "org.mediahub.mediaseed" or value not in {"administrator", "user", "viewer", "denied"} for key, value in app_roles.items()):
                raise DomainError("invalid_app_roles", "Invalid app permissions")
            if user and user.role == "administrator" and target_role != "administrator":
                admins = list(db.scalars(select(User.id).where(User.role == "administrator")))
                if len(admins) <= 1:
                    raise DomainError("protected_user", "Cannot demote the last administrator", 409)
            duplicate = db.scalar(select(User).where(User.username == username))
            if duplicate and duplicate.id != user_id:
                raise DomainError("username_exists", "Username already exists", 409)
            if user is None:
                user = User(username=username, password_hash=hasher.hash(password), role=target_role)
                db.add(user)
            else:
                user.username = username
                user.role = target_role
                if password:
                    user.password_hash = hasher.hash(password)
                    db.execute(delete(Session).where(Session.user_id == user.id))
            db.flush()
            if app_roles is not None:
                key = "app_roles:" + user.id
                row = db.scalar(select(Setting).where(Setting.key == key))
                if row:
                    row.value = app_roles
                else:
                    db.add(Setting(key=key, value=app_roles))
                db.flush()
            return {**self.public_user(user), "appRoles": self.app_roles(db, user.id)}

    def delete_user(self, user_id, actor_id):
        with self.sessions.begin() as db:
            user = db.get(User, user_id)
            if user is None:
                raise DomainError("user_not_found", "User not found", 404)
            administrators = list(db.scalars(select(User.id).where(User.role == "administrator")))
            if user_id == actor_id or (user.role == "administrator" and len(administrators) <= 1):
                raise DomainError("protected_user", "Cannot delete your own account or the last administrator", 409)
            db.execute(delete(Session).where(Session.user_id == user_id))
            db.execute(delete(UserSecurity).where(UserSecurity.user_id == user_id))
            db.execute(delete(Setting).where(Setting.key == "app_roles:" + user_id))
            db.delete(user)

    def throttle(self, client: str):
        clock = time.time()
        self.attempts = {
            k: [v for v in values if v > clock - 60]
            for k, values in self.attempts.items()
            if values[-1] > clock - 60
        }
        values = self.attempts.setdefault(client, [])
        if len(values) >= 5 or len(self.attempts) > 1000:
            raise DomainError(
                "rate_limited", "Too many login attempts. Try again in one minute.", 429
            )
        values.append(clock)
        return clock

    def login(self, username: str, password: str, client: str, second_factor: str = ""):
        clock = self.throttle("login:" + client)
        self.throttle("account:" + username.strip().lower())
        with self.sessions.begin() as db:
            user = db.scalar(select(User).where(User.username == username.strip().lower()))
            try:
                valid = hasher.verify(user.password_hash if user else DUMMY_HASH, password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid or user is None:
                raise DomainError("invalid_credentials", "Incorrect username or password", 401)
            security = db.get(UserSecurity, user.id)
            if security and security.enabled:
                if not second_factor:
                    raise DomainError(
                        "second_factor_required", "Enter your authenticator or recovery code", 401
                    )
                self.mfa.verify(db, security, second_factor)
            if hasher.check_needs_rehash(user.password_hash):
                user.password_hash = hasher.hash(password)
            db.execute(delete(Session).where(Session.expires_at <= int(clock)))
            token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            db.add(
                Session(
                    user_id=user.id,
                    token_hash=digest(token),
                    csrf_token=csrf,
                    expires_at=int(clock + self.config.session_hours * 3600),
                )
            )
            public = {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "csrf": csrf,
                "totpEnabled": bool(security and security.enabled),
            }
        self.events.record("user.logged_in", "auth", "Administrator signed in")
        return token, public

    def authenticate(self, token: str | None):
        if not token:
            raise DomainError("unauthorized", "Sign in to continue", 401)
        with self.sessions() as db:
            session = db.scalar(
                select(Session).where(
                    Session.token_hash == digest(token), Session.expires_at > int(time.time())
                )
            )
            if session is None:
                raise DomainError("unauthorized", "Session expired. Sign in again.", 401)
            user = db.get(User, session.user_id)
            if user is None:
                raise DomainError("unauthorized", "Sign in to continue", 401)
            return {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "csrf": session.csrf_token,
                "totpEnabled": bool(
                    (security := db.get(UserSecurity, user.id)) and security.enabled
                ),
                "totpRequired": bool(
                    (
                        policy := db.scalar(
                            select(Setting).where(Setting.key == "authentication_policy")
                        )
                    )
                    and policy.value.get("requireTotp")
                ),
            }

    def reauthenticate(self, db, user_id, password, code=""):
        self.throttle("security:" + user_id)
        user = db.get(User, user_id)
        try:
            valid = user is not None and hasher.verify(user.password_hash, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise DomainError("reauthentication_failed", "Current password is incorrect", 401)
        row = db.get(UserSecurity, user_id)
        if row and row.enabled:
            self.mfa.verify(db, row, code)
        return user

    @staticmethod
    def authenticate_session_policy(db, user):
        policy = db.scalar(select(Setting).where(Setting.key == "authentication_policy"))
        security = db.get(UserSecurity, user.id)
        if policy and policy.value.get("requireTotp") and not (security and security.enabled):
            raise DomainError("enrollment_required", "Set up two-factor authentication to continue", 403)

    def logout(self, token: str):
        with self.sessions.begin() as db:
            db.execute(delete(Session).where(Session.token_hash == digest(token)))
