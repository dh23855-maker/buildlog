from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import ApiError
from app.models.session import LoginSession
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest, UserResponse
from app.security import (
    SESSION_COOKIE_NAME,
    SESSION_DAYS,
    find_login_session,
    get_current_user,
    hash_password,
    hash_session_token,
    new_session_token,
    session_expires_at,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_TAKEN = "이미 사용 중인 이메일입니다. 다른 이메일을 입력해 주세요."
NICKNAME_TAKEN = "이미 사용 중인 닉네임입니다. 다른 닉네임을 입력해 주세요."
LOGIN_FAILED = "이메일 또는 비밀번호가 맞지 않습니다."


def nickname_in_use(db: Session, nickname: str, except_user_id: int | None = None) -> bool:
    query = select(User.id).where(func.lower(User.nickname) == nickname.lower())
    if except_user_id is not None:
        query = query.where(User.id != except_user_id)
    return db.scalar(query) is not None


@router.post("/signup", response_model=UserResponse, status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> User:
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise ApiError(409, EMAIL_TAKEN, "email")
    if nickname_in_use(db, body.nickname):
        raise ApiError(409, NICKNAME_TAKEN, "nickname")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        nickname=body.nickname,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 거의 동시에 같은 값으로 가입한 경우를 데이터베이스가 막아 준 것입니다.
        db.rollback()
        if db.scalar(select(User.id).where(User.email == body.email)) is not None:
            raise ApiError(409, EMAIL_TAKEN, "email") from None
        raise ApiError(409, NICKNAME_TAKEN, "nickname") from None
    return user


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.email == body.email))
    # 이메일이 없어도 비밀번호 확인과 같은 시간이 걸리게 하고, 실패 이유는 하나로만 알려줍니다.
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        raise ApiError(401, LOGIN_FAILED)

    # 이 사용자의 만료된 로그인 표를 정리합니다.
    db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id, LoginSession.expires_at <= datetime.now(UTC)
        )
    )
    token = new_session_token()
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=session_expires_at(),
        )
    )
    db.commit()

    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,  # 화면의 JavaScript가 읽을 수 없습니다.
        samesite="lax",
        secure=settings.app_env == "production",  # 실제 서비스(https)에서만 켭니다.
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> None:
    # 이미 로그아웃된 쿠키로 다시 눌러도 오류 없이 쿠키만 지웁니다.
    login_session = find_login_session(db, token)
    if login_session is not None:
        db.delete(login_session)
        db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user
