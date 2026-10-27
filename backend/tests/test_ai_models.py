from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.models.ai_usage import AiUsage
from app.models.material import Material
from app.models.user import User
from app.security import hash_password

BACKEND_DIR = Path(__file__).resolve().parent.parent

NEW_COLUMNS = {"summary", "analysis_status", "analysis_error", "analyzed_at", "analysis_model"}


def make_user(db, email="a@example.com", nickname="사용자A") -> User:
    user = User(email=email, password_hash=hash_password("password123"), nickname=nickname)
    db.add(user)
    db.commit()
    return user


def make_material(user_id, **overrides) -> Material:
    values = {
        "user_id": user_id,
        "title": "제목",
        "kind": "image",
        "original_filename": "a.png",
        "content_type": "image/png",
        "size_bytes": 10,
        "storage_name": "a" * 32 + ".png",
    }
    values.update(overrides)
    return Material(**values)


# ---------- materials 분석 열 ----------


def test_새_자료의_분석_기본값은_skipped이고_요약은_비어_있다(db):
    user = make_user(db)
    db.add(make_material(user.id))
    db.commit()

    saved = db.scalar(select(Material))
    assert saved.analysis_status == "skipped"
    assert saved.summary is None
    assert saved.analysis_error is None
    assert saved.analyzed_at is None
    assert saved.analysis_model is None


def test_분석_결과를_저장할_수_있다(db):
    user = make_user(db)
    db.add(
        make_material(
            user.id,
            summary="요약 내용\n- 핵심 1",
            analysis_status="done",
            analyzed_at=datetime(2026, 10, 27, 9, 0, tzinfo=UTC),
            analysis_model="gpt-6-luna",
        )
    )
    db.commit()
    saved = db.scalar(select(Material))
    assert saved.summary == "요약 내용\n- 핵심 1"
    assert saved.analysis_status == "done"
    assert saved.analysis_model == "gpt-6-luna"


def test_긴_요약도_저장된다(db):
    user = make_user(db)
    db.add(make_material(user.id, summary="가" * 5000, analysis_status="done"))
    db.commit()
    assert len(db.scalar(select(Material)).summary) == 5000


@pytest.mark.parametrize("status", ["pending", "done", "failed", "skipped"])
def test_허용하는_분석_상태는_저장된다(db, status):
    user = make_user(db)
    db.add(make_material(user.id, analysis_status=status))
    db.commit()
    assert db.scalar(select(Material)).analysis_status == status


@pytest.mark.parametrize("status", ["running", "DONE", "", "success"])
def test_허용하지_않는_분석_상태는_데이터베이스가_막는다(db, status):
    user = make_user(db)
    db.add(make_material(user.id, analysis_status=status))
    with pytest.raises(IntegrityError):
        db.commit()


def test_분석_상태를_비울_수_없다(db):
    user = make_user(db)
    # ORM은 None 대신 기본값(skipped)을 채우므로, 데이터베이스가 직접 막는지 SQL로 확인합니다.
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO materials (user_id, title, kind, original_filename, content_type, size_bytes, "
                "storage_name, created_at, analysis_status) VALUES (:u, 'x', 'image', 'a.png', 'image/png', 10, "
                "'n.png', '2026-10-20', NULL)"
            ),
            {"u": user.id},
        )
    db.rollback()


def test_상태를_지정하지_않으면_기본값_skipped가_채워진다_ORM과_SQL_모두(db):
    user = make_user(db)
    db.execute(
        text(
            "INSERT INTO materials (user_id, title, kind, original_filename, content_type, size_bytes, "
            "storage_name, created_at) VALUES (:u, 'x', 'image', 'a.png', 'image/png', 10, 'd.png', '2026-10-20')"
        ),
        {"u": user.id},
    )
    db.commit()
    assert db.scalar(select(Material.analysis_status)) == "skipped"


# ---------- ai_usage ----------


def test_하루_사용_횟수를_저장한다(db):
    user = make_user(db)
    db.add(AiUsage(user_id=user.id, day=date(2026, 10, 27), count=3))
    db.commit()
    saved = db.scalar(select(AiUsage))
    assert (saved.user_id, saved.day, saved.count) == (user.id, date(2026, 10, 27), 3)


def test_같은_사용자의_같은_날짜는_한_줄만_있다(db):
    user = make_user(db)
    db.add(AiUsage(user_id=user.id, day=date(2026, 10, 27), count=1))
    db.commit()
    db.add(AiUsage(user_id=user.id, day=date(2026, 10, 27), count=2))
    with pytest.raises(IntegrityError):
        db.commit()


def test_날짜가_다르거나_사용자가_다르면_따로_센다(db):
    a = make_user(db, "a@example.com", "사용자A")
    b = make_user(db, "b@example.com", "사용자B")
    db.add_all(
        [
            AiUsage(user_id=a.id, day=date(2026, 10, 27), count=1),
            AiUsage(user_id=a.id, day=date(2026, 10, 28), count=1),
            AiUsage(user_id=b.id, day=date(2026, 10, 27), count=1),
        ]
    )
    db.commit()
    assert len(db.scalars(select(AiUsage)).all()) == 3


def test_횟수는_음수가_될_수_없다(db):
    user = make_user(db)
    db.add(AiUsage(user_id=user.id, day=date(2026, 10, 27), count=-1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_없는_사용자의_횟수는_저장할_수_없다(db):
    db.add(AiUsage(user_id=9999, day=date(2026, 10, 27), count=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_자료를_지워도_횟수는_남고_사용자를_지우면_횟수도_함께_지워진다(db):
    a = make_user(db, "a@example.com", "사용자A")
    b = make_user(db, "b@example.com", "사용자B")
    material = make_material(a.id)
    db.add_all(
        [
            material,
            AiUsage(user_id=a.id, day=date(2026, 10, 27), count=2),
            AiUsage(user_id=b.id, day=date(2026, 10, 27), count=1),
        ]
    )
    db.commit()

    # 자료를 지워도 하루 횟수는 돌아오지 않는다 (한도를 우회할 수 없다)
    db.delete(material)
    db.commit()
    assert db.scalar(select(AiUsage).where(AiUsage.user_id == a.id)).count == 2

    # 사용자를 지우면 그 사용자의 횟수도 함께 지워진다
    db.delete(a)
    db.commit()
    assert [u.user_id for u in db.scalars(select(AiUsage))] == [b.id]


# ---------- 마이그레이션 0004 ----------

USER_SQL = (
    "INSERT INTO users (id, email, password_hash, nickname, is_admin, created_at) "
    "VALUES (1, 'a@example.com', 'x', '사용자A', 0, '2026-10-20 00:00:00')"
)


def _config(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.sqlite3').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config, create_engine(url)


def test_0004를_적용하면_기존_자료는_skipped가_되고_규칙이_생긴다(tmp_path):
    config, engine = _config(tmp_path)
    command.upgrade(config, "0003")
    with engine.begin() as conn:
        conn.execute(text(USER_SQL))
        conn.execute(
            text(
                "INSERT INTO materials (id, user_id, title, kind, original_filename, content_type, size_bytes, "
                "storage_name, created_at) VALUES (1, 1, '옛 자료', 'image', 'a.png', 'image/png', 10, 'old.png', "
                "'2026-10-20 00:00:00')"
            )
        )

    command.upgrade(config, "0004")

    insp = inspect(engine)
    assert NEW_COLUMNS <= {c["name"] for c in insp.get_columns("materials")}
    assert "ai_usage" in insp.get_table_names()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT title, analysis_status, summary FROM materials")).one()
    assert tuple(row) == ("옛 자료", "skipped", None)  # 기존 자료는 그대로이고 상태만 skipped

    # 새 규칙과 기존 규칙이 모두 살아 있다
    checks = {c["name"] for c in insp.get_check_constraints("materials")}
    assert {
        "ck_materials_kind",
        "ck_materials_content_type",
        "ck_materials_size_positive",
        "ck_materials_analysis_status",
    } <= checks
    assert "ix_materials_user_created" in {i["name"] for i in insp.get_indexes("materials")}

    # 새 규칙이 실제로 잘못된 상태를 막는다
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO materials (user_id, title, kind, original_filename, content_type, size_bytes, "
                "storage_name, created_at, analysis_status) VALUES (1, 'x', 'image', 'a.png', 'image/png', 10, "
                "'bad.png', '2026-10-20', 'running')"
            )
        )


def test_0004를_되돌리면_0003_상태가_되고_자료는_남는다(tmp_path):
    config, engine = _config(tmp_path)
    command.upgrade(config, "0004")
    with engine.begin() as conn:
        conn.execute(text(USER_SQL))
        conn.execute(
            text(
                "INSERT INTO materials (user_id, title, kind, original_filename, content_type, size_bytes, "
                "storage_name, created_at, analysis_status, summary) VALUES (1, '자료', 'image', 'a.png', "
                "'image/png', 10, 'a.png', '2026-10-20', 'done', '요약')"
            )
        )

    command.downgrade(config, "0003")

    insp = inspect(engine)
    assert NEW_COLUMNS.isdisjoint({c["name"] for c in insp.get_columns("materials")})
    assert "ai_usage" not in insp.get_table_names()
    checks = {c["name"] for c in insp.get_check_constraints("materials")}
    assert "ck_materials_analysis_status" not in checks
    assert "ck_materials_kind" in checks  # 기존 규칙은 유지
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM materials")).scalar() == "자료"  # 자료 자체는 남음

    command.upgrade(config, "head")  # 다시 올려도 문제없다
    assert "ai_usage" in inspect(engine).get_table_names()
