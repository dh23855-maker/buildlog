from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.session import LoginSession
from app.models.user import User
from app.security import SESSION_COOKIE_NAME
from tests.conftest import signup_payload


def signup(client, **overrides):
    return client.post("/api/auth/signup", json=signup_payload(**overrides))


def login(client, signed_up, **overrides):
    payload = {"email": signed_up["email"], "password": signed_up["password"], **overrides}
    return client.post("/api/auth/login", json=payload)


class TestSignup:
    def test_가입하면_계정이_만들어진다(self, client, db):
        response = signup(client)
        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "user@example.com"
        assert body["nickname"] == "빌드로그"
        assert "password" not in str(body)
        assert db.scalar(select(User)).password_hash != "password123"

    def test_이메일은_공백을_지우고_소문자로_저장된다(self, client, db):
        signup(client, email="  User@Example.COM  ")
        assert db.scalar(select(User)).email == "user@example.com"

    def test_같은_이메일로_두_번_가입할_수_없다(self, client):
        signup(client)
        response = signup(client, nickname="다른닉")
        assert response.status_code == 409
        assert response.json()["field"] == "email"

    def test_대소문자만_다른_이메일도_중복이다(self, client):
        signup(client)
        response = signup(client, email="USER@example.com", nickname="다른닉")
        assert response.status_code == 409

    def test_이미_쓰는_닉네임으로_가입할_수_없다(self, client):
        signup(client)
        response = signup(client, email="b@example.com")
        assert response.status_code == 409
        assert response.json()["field"] == "nickname"

    @pytest.mark.parametrize("email", ["abc", "abc@", "@example.com", "a b@example.com", "a@b", ""])
    def test_잘못된_이메일은_가입할_수_없다(self, client, email):
        response = signup(client, email=email)
        assert response.status_code == 422
        assert response.json()["field"] == "email"

    @pytest.mark.parametrize("length", [8, 64])
    def test_비밀번호_8자와_64자는_가능하다(self, client, length):
        assert signup(client, password="a" * length).status_code == 201

    @pytest.mark.parametrize("length", [7, 65])
    def test_비밀번호_7자와_65자는_불가능하다(self, client, length):
        response = signup(client, password="a" * length)
        assert response.status_code == 422
        assert response.json()["field"] == "password"

    def test_비밀번호_앞뒤_공백은_지우지_않는다(self, client):
        assert signup(client, password="  1234  ").status_code == 201
        ok = client.post("/api/auth/login", json={"email": "user@example.com", "password": "  1234  "})
        assert ok.status_code == 200

    @pytest.mark.parametrize("nickname", ["가나", "ab", "a" * 20, "한글_English_123"])
    def test_허용되는_닉네임(self, client, nickname):
        assert signup(client, nickname=nickname).status_code == 201

    @pytest.mark.parametrize(
        "nickname", ["a", "가", "a" * 21, "공백 포함", "특수!", "a-b", "이모지😀", "   ", ""]
    )
    def test_허용되지_않는_닉네임(self, client, nickname):
        response = signup(client, nickname=nickname)
        assert response.status_code == 422
        assert response.json()["field"] == "nickname"

    def test_닉네임_앞뒤_공백은_지운다(self, client):
        assert signup(client, nickname="  가나다  ").json()["nickname"] == "가나다"

    def test_빠진_항목은_안내를_돌려준다(self, client):
        response = client.post("/api/auth/signup", json={"email": "a@example.com"})
        assert response.status_code == 422
        assert response.json()["detail"]


class TestLogin:
    def test_맞는_정보로_로그인된다(self, client, signed_up):
        response = login(client, signed_up)
        assert response.status_code == 200
        assert response.json()["nickname"] == "빌드로그"
        assert client.get("/api/auth/me").status_code == 200

    def test_이메일_대소문자와_공백은_무시한다(self, client, signed_up):
        assert login(client, signed_up, email=" USER@Example.com ").status_code == 200

    def test_쿠키는_httpOnly이고_DB에는_원문이_없다(self, client, signed_up, db):
        response = login(client, signed_up)
        cookie_header = response.headers["set-cookie"].lower()
        assert "httponly" in cookie_header
        assert "samesite=lax" in cookie_header
        token = response.cookies[SESSION_COOKIE_NAME]
        stored = db.scalar(select(LoginSession))
        assert stored.token_hash != token
        assert token not in stored.token_hash

    def test_틀린_비밀번호는_로그인되지_않는다(self, client, signed_up):
        response = login(client, signed_up, password="wrong-pass")
        assert response.status_code == 401
        assert response.json()["detail"] == "이메일 또는 비밀번호가 맞지 않습니다."
        assert client.get("/api/auth/me").status_code == 401

    def test_없는_이메일도_같은_메시지다(self, client, signed_up):
        wrong_pw = login(client, signed_up, password="wrong-pass")
        no_user = login(client, signed_up, email="none@example.com")
        assert no_user.status_code == 401
        assert no_user.json() == wrong_pw.json()

    def test_만료된_로그인_표는_거부된다(self, client, logged_in, db):
        stored = db.scalar(select(LoginSession))
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert client.get("/api/auth/me").status_code == 401

    def test_로그인_유지는_7일이다(self, client, signed_up, db):
        response = login(client, signed_up)
        assert "max-age=604800" in response.headers["set-cookie"].lower()
        expires_at = db.scalar(select(LoginSession)).expires_at.replace(tzinfo=UTC)
        assert timedelta(days=6, hours=23) < expires_at - datetime.now(UTC) <= timedelta(days=7)


class TestLogout:
    def test_로그아웃하면_예전_쿠키로_요청이_거부된다(self, client, logged_in, db):
        old_cookie = client.cookies[SESSION_COOKIE_NAME]
        assert client.post("/api/auth/logout").status_code == 204
        assert db.scalars(select(LoginSession)).all() == []
        assert client.get("/api/auth/me").status_code == 401

        # 예전 쿠키를 그대로 다시 보내도 거부됩니다.
        client.cookies.set(SESSION_COOKIE_NAME, old_cookie)
        assert client.get("/api/auth/me").status_code == 401

    def test_로그아웃해도_계정은_남고_다시_로그인된다(self, client, logged_in, signed_up, db):
        client.post("/api/auth/logout")
        assert db.scalar(select(User)) is not None
        assert login(client, signed_up).status_code == 200

    def test_내_로그인만_끝난다(self, make_client, signed_up):
        first, second = make_client(), make_client()
        for c in (first, second):
            login(c, signed_up)
        first.post("/api/auth/logout")
        assert first.get("/api/auth/me").status_code == 401
        assert second.get("/api/auth/me").status_code == 200

    def test_로그인하지_않아도_로그아웃은_오류가_없다(self, client):
        assert client.post("/api/auth/logout").status_code == 204


def test_로그인하지_않으면_내_정보를_볼_수_없다(client):
    assert client.get("/api/auth/me").status_code == 401
