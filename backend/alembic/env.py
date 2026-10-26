"""Alembic 실행 설정: 앱과 같은 DATABASE_URL, 같은 모델을 사용합니다."""

from alembic import context
from sqlalchemy import create_engine

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
    # app.database를 불러올 때 SQLite 폴더가 만들어지지만, 다른 주소일 때를 위해 엔진을 새로 만듭니다.
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite에서도 표 구조를 안전하게 바꾸기 위함
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
