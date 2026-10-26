"""비밀번호 보호, 로그인 표 만들기, 로그인 확인을 담당합니다."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.models.session import LoginSession
from app.models.user import User

SESSION_COOKIE_NAME = "buildlog_session"
SESSION_DAYS = 7

# Argon2: 비밀번호를 되돌릴 수 없는 값으로 바꾸는 방식입니다.
_password_hash = PasswordHash.recommended()
# 없는 이메일로 로그인할 때도 같은 시간이 걸리도록 쓰는 가짜 값입니다.
_DUMMY_HASH = _password_hash.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    return _password_hash.verify(password, password_hash)


def new_session_token() -> str:
    """추측할 수 없는 임의의 로그인 표 값을 만듭니다. 쿠키에만 담깁니다."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """데이터베이스에는 로그인 표 원문 대신 변환한 값만 저장합니다."""
    return hashlib.sha256(token.encode()).hexdigest()


def session_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(days=SESSION_DAYS)


def find_login_session(db: Session, token: str | None) -> LoginSession | None:
    """쿠키의 로그인 표가 유효하면 데이터베이스의 로그인 표를 돌려줍니다."""
    if not token:
        return None
    login_session = db.scalar(
        select(LoginSession).where(LoginSession.token_hash == hash_session_token(token))
    )
    if login_session is None:
        return None
    expires_at = login_session.expires_at
    if expires_at.tzinfo is None:  # SQLite는 시간대 정보를 저장하지 않으므로 UTC로 봅니다.
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        return None
    return login_session


def get_current_user(
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> User:
    """로그인한 사용자만 통과시킵니다. 기록 요청 주소들이 공통으로 사용합니다."""
    login_session = find_login_session(db, token)
    if login_session is None:
        raise ApiError(401, "로그인이 필요합니다.")
    user = db.get(User, login_session.user_id)
    if user is None:
        raise ApiError(401, "로그인이 필요합니다.")
    return user
