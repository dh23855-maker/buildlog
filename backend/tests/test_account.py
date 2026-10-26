import pytest
from sqlalchemy import select

from app.models.user import User
from tests.conftest import signup_payload


def change(client, nickname):
    return client.patch("/api/account/nickname", json={"nickname": nickname})


def test_로그인하지_않으면_닉네임을_바꿀_수_없다(client):
    assert change(client, "새닉네임").status_code == 401


def test_사용하지_않은_닉네임으로_바뀐다(logged_in, db):
    response = change(logged_in, "새닉네임")
    assert response.status_code == 200
    assert response.json()["nickname"] == "새닉네임"
    assert logged_in.get("/api/auth/me").json()["nickname"] == "새닉네임"
    assert db.scalar(select(User)).nickname == "새닉네임"


def test_내_닉네임_그대로나_대소문자만_바꾸는_것은_가능하다(logged_in):
    assert change(logged_in, "빌드로그").status_code == 200
    assert change(logged_in, "BuildLog").status_code == 200
    assert change(logged_in, "buildlog").status_code == 200


def test_다른_사람이_쓰는_닉네임으로는_바꿀_수_없다(logged_in, make_client):
    other = make_client()
    other.post("/api/auth/signup", json=signup_payload(email="b@example.com", nickname="남의닉"))
    response = change(logged_in, "남의닉")
    assert response.status_code == 409
    assert response.json()["field"] == "nickname"
    assert logged_in.get("/api/auth/me").json()["nickname"] == "빌드로그"


@pytest.mark.parametrize("nickname", ["a", "a" * 21, "공백 포함", "특수!", "   ", ""])
def test_닉네임_규칙에_맞지_않으면_바뀌지_않는다(logged_in, nickname):
    assert change(logged_in, nickname).status_code == 422
    assert logged_in.get("/api/auth/me").json()["nickname"] == "빌드로그"


@pytest.mark.parametrize("nickname", ["가나", "a" * 20])
def test_닉네임_경계값은_가능하다(logged_in, nickname):
    assert change(logged_in, nickname).status_code == 200


def test_닉네임_앞뒤_공백은_지운다(logged_in):
    assert change(logged_in, "  새닉네임  ").json()["nickname"] == "새닉네임"


def test_요청으로_다른_사용자를_지정할_방법이_없다(logged_in, make_client, db):
    other = make_client()
    other_id = other.post(
        "/api/auth/signup", json=signup_payload(email="b@example.com", nickname="남의닉")
    ).json()["id"]
    logged_in.patch(
        "/api/account/nickname", json={"nickname": "새닉네임", "id": other_id, "user_id": other_id}
    )
    assert db.get(User, other_id).nickname == "남의닉"
