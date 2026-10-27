import os
import tempfile
from pathlib import Path

# 앱을 불러오기 전에 테스트 전용 SQLite 파일을 가리키게 합니다.
# 개발용 데이터 파일(database/buildlog.sqlite3)은 테스트가 절대 건드리지 않습니다.
_TEST_DIR = tempfile.mkdtemp(prefix="buildlog-test-")
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(_TEST_DIR) / 'test.sqlite3').as_posix()}"
# 개발자의 실제 OpenAI 키가 backend/.env에 있어도 테스트는 키가 없는 상태로 시작합니다.
# (환경 변수가 .env보다 우선합니다.) 테스트가 실수로 실제 OpenAI를 호출해 비용이 드는 일을 막기 위해서입니다.
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_MODEL"] = ""
os.environ["AI_DAILY_LIMIT"] = "30"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    """업로드 파일은 테스트마다 임시 폴더에 저장되어, 실제 backend/uploads를 건드리지 않습니다."""
    import app.config

    upload_dir = tmp_path / "uploads" / "materials"
    monkeypatch.setattr(app.config, "MATERIALS_UPLOAD_DIR", upload_dir)
    return upload_dir


import app.openai_client as _openai_client  # noqa: E402

_REAL_CREATE_CLIENT = _openai_client.create_client


@pytest.fixture(autouse=True)
def no_real_openai(monkeypatch):
    """모든 테스트에서 실제 OpenAI 클라이언트를 만들 수 없게 합니다. AI를 시험하는 테스트는 가짜 클라이언트를 직접 넘깁니다."""

    def blocked(*args, **kwargs):
        raise AssertionError("테스트에서 실제 OpenAI 클라이언트를 만들 수 없습니다. 가짜 클라이언트를 사용하세요.")

    monkeypatch.setattr(_openai_client, "create_client", blocked)


@pytest.fixture
def real_create_client():
    """create_client 자체를 시험할 때만 쓰는 원래 함수입니다."""
    return _REAL_CREATE_CLIENT


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
