from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app import models
from app.core.errors import AuthRequiredError
from app.database import get_db
from app.core.config import settings
from app.services.auth_service import user_for_session


def current_user(
    token: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    db: Session = Depends(get_db),
) -> models.User:
    user = user_for_session(db, token)
    if user is None:
        raise AuthRequiredError("请登录后继续")
    return user
