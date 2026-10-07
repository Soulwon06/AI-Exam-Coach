import re

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.core.errors import AppError, AuthRequiredError, InvalidRequestError
from app.database import get_db
from app.deps import current_user
from app.services import auth_service

router = APIRouter()

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
_DUMMY_PASSWORD_HASH = auth_service.hash_password("invalid-login-timing-placeholder")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class RegisterCredentials(Credentials):
    password: str = Field(min_length=8, max_length=128)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/auth/register")
def register(payload: RegisterCredentials, response: Response, db: Session = Depends(get_db)):
    username = auth_service.normalize_username(payload.username)
    if not _USERNAME_PATTERN.fullmatch(username):
        raise InvalidRequestError("用户名只能包含字母、数字、下划线或连字符（3–32 位）")
    if settings.demo_username and username == auth_service.normalize_username(settings.demo_username):
        raise AppError("USERNAME_RESERVED", "该用户名不可注册", status_code=409)
    if db.query(models.AuthAccount).filter(models.AuthAccount.username == username).first():
        raise AppError("USERNAME_ALREADY_REGISTERED", "该用户名已注册，请直接登录", status_code=409)

    user = models.User()
    db.add(user)
    db.flush()
    db.add(models.AuthAccount(user_id=user.id, username=username, password_hash=auth_service.hash_password(payload.password)))
    db.flush()
    token = auth_service.create_session(db, user)
    _set_session_cookie(response, token)
    return {"data": auth_service.public_user(user, db), "error": None}


@router.post("/auth/login")
def login(payload: Credentials, response: Response, db: Session = Depends(get_db)):
    username = auth_service.normalize_username(payload.username)
    account = db.query(models.AuthAccount).filter(models.AuthAccount.username == username).first()
    password_hash = account.password_hash if account else _DUMMY_PASSWORD_HASH
    password_ok = auth_service.verify_password(payload.password, password_hash)
    if account is None or not password_ok:
        raise AuthRequiredError("用户名或密码不正确")

    user = db.get(models.User, account.user_id)
    if user is None:
        raise AuthRequiredError("账号状态无效，请联系管理员")
    token = auth_service.create_session(db, user)
    _set_session_cookie(response, token)
    return {"data": auth_service.public_user(user, db), "error": None}


@router.get("/auth/me")
def me(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return {"data": auth_service.public_user(user, db), "error": None}


@router.post("/auth/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
):
    auth_service.revoke_session(db, token)
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )
    return {"data": {"logged_out": True}, "error": None}
