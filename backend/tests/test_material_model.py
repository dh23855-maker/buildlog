from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import app.config
from app.models.material import Material
from app.models.user import User
from app.security import hash_password

BACKEND_DIR = Path(__file__).resolve().parent.parent


def make_user(db, email="a@example.com", nickname="사용자A") -> User:
    user = User(email=email, password_hash=hash_password("password123"), nickname=nickname)
    db.add(user)
    db.commit()
    return user


def make_material(user_id: int, **overrides) -> Material:
    values = {
        "user_id": user_id,
        "title": "REST API 핵심 정리",
        "memo": None,
        "kind": "image",
        "original_filename": "rest.png",
        "content_type": "image/png",
        "size_bytes": 1234,
        "storage_name": "a" * 32 + ".png",
    }
    values.update(overrides)
    return Material(**values)


def test_자료가_저장되고_등록_시각이_채워진다(db):
    user = make_user(db)
    db.add(make_material(user.id, memo="메모"))
    db.commit()

    saved = db.scalar(select(Material))
    assert saved.title == "REST API 핵심 정리"
    assert saved.memo == "메모"
    assert saved.user_id == user.id
    assert saved.created_at is not None


def test_메모는_비워_둘_수_있다(db):
    user = make_user(db)
    db.add(make_material(user.id, memo=None))
    db.commit()
    assert db.scalar(select(Material)).memo is None


def test_같은_저장_이름은_두_번_쓸_수_없다(db):
    user = make_user(db)
    db.add(make_material(user.id, storage_name="same.png"))
    db.commit()
    db.add(make_material(user.id, storage_name="same.png"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_없는_사용자의_자료는_저장할_수_없다(db):
    db.add(make_material(user_id=9999))
    with pytest.raises(IntegrityError):
        db.commit()


def test_사용자를_지우면_그_사용자의_자료_정보도_함께_지워진다(db):
    a = make_user(db, "a@example.com", "사용자A")
    b = make_user(db, "b@example.com", "사용자B")
    db.add(make_material(a.id, storage_name="a.png"))
    db.add(make_material(b.id, storage_name="b.png"))
    db.commit()

    db.delete(a)
    db.commit()

    remaining = db.scalars(select(Material)).all()
    assert [m.storage_name for m in remaining] == ["b.png"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "audio"},
        {"content_type": "image/gif"},
        {"content_type": "image/svg+xml"},
        {"size_bytes": 0},
        {"size_bytes": -1},
    ],
)
def test_허용하지_않는_값은_데이터베이스가_막는다(db, overrides):
    user = make_user(db)
    db.add(make_material(user.id, **overrides))
    with pytest.raises(IntegrityError):
        db.commit()


def test_허용하는_세_가지_형식은_저장된다(db):
    user = make_user(db)
    db.add(make_material(user.id, storage_name="1.png", kind="image", content_type="image/png"))
    db.add(make_material(user.id, storage_name="2.jpg", kind="image", content_type="image/jpeg"))
    db.add(make_material(user.id, storage_name="3.mp4", kind="video", content_type="video/mp4"))
    db.commit()
    assert len(db.scalars(select(Material)).all()) == 3


def test_업로드_폴더는_backend_uploads_아래이고_테스트에서는_임시_폴더로_바뀐다(isolated_uploads):
    # 테스트 중에는 실제 폴더가 아니라 임시 폴더를 가리킵니다.
    assert app.config.MATERIALS_UPLOAD_DIR == isolated_uploads
    assert BACKEND_DIR / "uploads" not in isolated_uploads.parents


def test_크기_한도는_5MB와_30MB다():
    assert app.config.MATERIAL_MAX_IMAGE_BYTES == 5_242_880
    assert app.config.MATERIAL_MAX_VIDEO_BYTES == 31_457_280
