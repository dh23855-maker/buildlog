import os
import tempfile
from pathlib import Path

# 앱을 불러오기 전에 테스트 전용 SQLite 파일을 가리키게 합니다.
# 개발용 데이터 파일(database/buildlog.sqlite3)은 테스트가 절대 건드리지 않습니다.
_TEST_DIR = tempfile.mkdtemp(prefix="buildlog-test-")
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(_TEST_DIR) / 'test.sqlite3').as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database():
    """테스트마다 빈 표로 시작합니다."""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_client():
    """서로 다른 사용자(쿠키)를 흉내 내기 위해 클라이언트를 여러 개 만듭니다."""
    clients = []

    def _make() -> TestClient:
        test_client = TestClient(app)
        clients.append(test_client)
        return test_client

    yield _make
    for test_client in clients:
        test_client.close()


def signup_payload(**overrides):
    payload = {"email": "user@example.com", "password": "password123", "nickname": "빌드로그"}
    payload.update(overrides)
    return payload


@pytest.fixture
def signed_up(client):
    """가입만 해 둔 상태 (로그인은 하지 않음)."""
    assert client.post("/api/auth/signup", json=signup_payload()).status_code == 201
    return signup_payload()


@pytest.fixture
def logged_in(client, signed_up):
    response = client.post(
        "/api/auth/login", json={"email": signed_up["email"], "password": signed_up["password"]}
    )
    assert response.status_code == 200
    return client
