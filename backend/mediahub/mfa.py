"""TOTP with encrypted enrollment, atomic replay protection and one-use recovery."""

import hashlib
import io
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg
from sqlalchemy import update

from mediahub.db import Session, UserSecurity
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore


def recovery_digest(user_id, code):
    return hashlib.sha256((user_id + ":" + code.strip().upper()).encode()).hexdigest()


class MFAService:
    def __init__(self, config):
        self.store = SecretStore((config.data_dir / "security-secrets").resolve())

    def begin(self, db, user):
        row = db.get(UserSecurity, user.id)
        if row and row.enabled:
            raise DomainError("totp_enabled", "Two-factor authentication is already enabled", 409)
        if row is None:
            row = UserSecurity(user_id=user.id)
            db.add(row)
        secret = pyotp.random_base32()
        reference = "totp-" + secrets.token_hex(16)
        self.store.put(reference, secret.encode())
        row.secret_reference = reference
        row.pending_expires = int(time.time()) + 600
        row.last_counter = -1
        row.enabled = False
        row.recovery_hashes = []
        # Enrollment is the sole intentional disclosure of this newly generated
        # seed. Encode locally: never send it to a third-party QR service.
        uri = pyotp.TOTP(secret).provisioning_uri(user.username, issuer_name="MediaHub")
        image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
        output = io.BytesIO()
        image.save(output)
        return {"qrSvg": output.getvalue().decode(), "expiresIn": 600}

    def verify(self, db, row, code, *, allow_recovery=True):
        if allow_recovery:
            candidate = recovery_digest(row.user_id, code)
            old = list(row.recovery_hashes)
            if any(secrets.compare_digest(candidate, entry) for entry in old):
                changed = db.execute(
                    update(UserSecurity)
                    .where(
                        UserSecurity.user_id == row.user_id,
                        UserSecurity.recovery_hashes == old,
                    )
                    .values(recovery_hashes=[e for e in old if e != candidate])
                )
                if changed.rowcount == 1:
                    return
        if len(code) == 6 and code.isascii() and code.isdigit() and row.secret_reference:
            secret = self.store.get(row.secret_reference).decode()
            totp = pyotp.TOTP(secret)
            counter = int(time.time()) // 30
            for step in (counter, counter - 1, counter + 1):
                if step > row.last_counter and secrets.compare_digest(totp.at(step * 30), code):
                    changed = db.execute(
                        update(UserSecurity)
                        .where(
                            UserSecurity.user_id == row.user_id,
                            UserSecurity.last_counter < step,
                        )
                        .values(last_counter=step)
                    )
                    if changed.rowcount == 1:
                        return
        raise DomainError(
            "invalid_second_factor", "Enter a valid authenticator or recovery code", 401
        )

    def confirm(self, db, user_id, code):
        row = db.get(UserSecurity, user_id)
        if row is None or row.enabled or row.pending_expires < int(time.time()):
            raise DomainError("enrollment_expired", "Start authenticator setup again", 409)
        self.verify(db, row, code, allow_recovery=False)
        row.enabled = True
        row.pending_expires = 0
        codes = self.recovery_codes(row)
        # Existing password-only sessions cannot remain privileged after enrollment.
        db.query(Session).filter(Session.user_id == user_id).delete(synchronize_session=False)
        return {"enabled": True, "recoveryCodes": codes, "signInAgain": True}

    @staticmethod
    def recovery_codes(row):
        codes = [secrets.token_hex(10).upper() for _ in range(10)]
        row.recovery_hashes = [recovery_digest(row.user_id, value) for value in codes]
        return codes
