from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.database import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_구조_기록을_빈_데이터베이스에_적용하면_모델과_같다(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrated.sqlite3').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "head")

    engine = create_engine(url)
    assert {"users", "login_sessions"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []

    command.downgrade(config, "base")
    assert "users" not in inspect(engine).get_table_names()
