import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.security import hash_password, verify_password


def make_user(**overrides) -> User:
    values = {"email": "a@example.com", "password_hash": hash_password("password123"), "nickname": "tester"}
    values.update(overrides)
    return User(**values)


def test_다른_이메일과_닉네임으로_저장된다(db):
    db.add_all([make_user(), make_user(email="b@example.com", nickname="tester2")])
    db.commit()
    assert len(db.scalars(select(User)).all()) == 2


def test_기본값은_일반_사용자다(db):
    user = make_user()
    db.add(user)
    db.commit()
    assert user.is_admin is False
    assert user.created_at is not None


def test_같은_이메일은_저장할_수_없다(db):
    db.add(make_user())
    db.commit()
    db.add(make_user(nickname="other"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_같은_닉네임은_저장할_수_없다(db):
    db.add(make_user())
    db.commit()
    db.add(make_user(email="b@example.com"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_대소문자만_다른_닉네임도_중복이다(db):
    db.add(make_user(nickname="Tester"))
    db.commit()
    db.add(make_user(email="b@example.com", nickname="tester"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_비밀번호_원문은_저장되지_않는다(db):
    user = make_user()
    db.add(user)
    db.commit()
    assert "password123" not in user.password_hash
    assert verify_password("password123", user.password_hash)
    assert not verify_password("wrong-password", user.password_hash)
