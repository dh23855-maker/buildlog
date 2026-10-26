"""데이터베이스 연결을 만듭니다.

`DATABASE_URL`이 가리키는 데이터베이스(개발·테스트는 SQLite)에 SQLAlchemy로 연결합니다.
"""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_url = make_url(settings.database_url)
_is_sqlite = _url.get_backend_name() == "sqlite"

# SQLite 파일이 들어갈 폴더가 없으면 먼저 만듭니다. (database/ 폴더는 Git에 올라가지 않습니다.)
if _is_sqlite and _url.database and _url.database != ":memory:":
    Path(_url.database).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        # SQLite는 기본적으로 표 사이의 연결 규칙(외래 키)을 검사하지 않아 켜 줍니다.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """모든 표(모델)가 물려받는 기본 클래스입니다."""


def get_db() -> Iterator[Session]:
    """요청 하나가 쓰는 데이터베이스 연결을 빌려주고, 끝나면 닫습니다."""
    with SessionLocal() as db:
        yield db
