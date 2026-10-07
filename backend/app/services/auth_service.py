"""Password and cookie-session helpers for the first-party web application."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models
from app.core.config import settings

_PBKDF2_ITERATIONS = 310_000


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_session(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    db.add(
        models.AuthSession(
            user_id=user.id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + timedelta(hours=settings.auth_session_ttl_hours),
        )
    )
    db.commit()
    return token


def user_for_session(db: Session, token: str | None) -> models.User | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.query(models.AuthSession).filter(models.AuthSession.token_hash == token_hash).first()
    if session is None:
        return None
    if session.expires_at <= datetime.utcnow():
        db.delete(session)
        db.commit()
        return None
    return db.get(models.User, session.user_id)


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.query(models.AuthSession).filter(models.AuthSession.token_hash == token_hash).first()
    if session is not None:
        db.delete(session)
        db.commit()


def is_demo_user(user: models.User, db: Session) -> bool:
    if settings.demo_user_id and user.id == settings.demo_user_id:
        return True
    if settings.demo_course_id:
        course = db.get(models.Course, settings.demo_course_id)
        return bool(course and course.user_id == user.id)
    return False


def provision_configured_account(db: Session) -> None:
    """Ensure the configured shared username points at its prepared course owner."""
    username = normalize_username(settings.demo_username)
    if not username or len(settings.demo_password) < 8:
        return

    if settings.demo_course_id:
        course = db.get(models.Course, settings.demo_course_id)
        if course is None:
            raise RuntimeError("Configured prepared course does not exist")
        user = db.get(models.User, course.user_id)
        if user is None:
            raise RuntimeError("Configured prepared course owner does not exist")
    else:
        user = db.get(models.User, settings.demo_user_id)
        if user is None:
            user = models.User(id=settings.demo_user_id)
            db.add(user)
            db.flush()

    account = db.query(models.AuthAccount).filter(models.AuthAccount.username == username).first()
    if account is not None and account.user_id != user.id:
        raise RuntimeError("Configured username is already assigned to another user")

    owner_account = db.query(models.AuthAccount).filter(models.AuthAccount.user_id == user.id).first()
    if owner_account is not None and owner_account.username != username:
        raise RuntimeError("Prepared course owner already has a different username")

    if account is None:
        account = models.AuthAccount(user_id=user.id, username=username, password_hash=hash_password(settings.demo_password))
        db.add(account)
    elif not verify_password(settings.demo_password, account.password_hash):
        account.password_hash = hash_password(settings.demo_password)
    db.commit()


def public_user(user: models.User, db: Session) -> dict[str, str | bool]:
    account = db.query(models.AuthAccount).filter(models.AuthAccount.user_id == user.id).first()
    demo = is_demo_user(user, db)
    return {"id": user.id, "username": account.username if account else "", "is_demo": demo}
