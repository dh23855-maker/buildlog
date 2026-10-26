from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 이메일은 항상 소문자로 저장하므로 대소문자만 다른 이메일은 중복으로 걸립니다.
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(20), nullable=False)
    # 운영자 여부. 기본은 일반 사용자이며 서버 명령으로만 바꿉니다.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


# 대소문자만 다른 닉네임도 같은 닉네임으로 봅니다. (SQLite와 PostgreSQL 모두 지원)
Index("uq_users_nickname_lower", func.lower(User.nickname), unique=True)
