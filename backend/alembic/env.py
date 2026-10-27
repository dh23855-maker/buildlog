"""Alembic 실행 설정: 앱과 같은 DATABASE_URL, 같은 모델을 사용합니다."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

import app.models  # noqa: F401  (모든 모델을 불러와 Alembic이 알게 합니다)
from app.config import settings
from app.database import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    # 테스트 등에서 alembic.ini 값으로 주소를 직접 넘기면 그것을 우선합니다.
    return config.get_main_option("sqlalchemy.url") or settings.database_url


def run_migrations() -> None:
    url = _database_url()
    engine = create_engine(url, connect_args={} if url.startswith("sqlite") else {"connect_timeout": 10})
    try:
        connection = engine.connect()
    except OperationalError as error:
        # 오류 원문에는 접속 정보가 섞일 수 있어 출력하지 않습니다.
        raise SystemExit(
            "데이터베이스에 연결하지 못했습니다. ("
            + type(error.orig).__name__
            + ")\n확인할 것: 비밀번호, 프로젝트 ID(postgres.xxxx), Session pooler 주소와 포트(5432), 인터넷 연결"
        ) from None
    with connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),  # SQLite에서만 표 구조 변경 방식을 바꿉니다
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
