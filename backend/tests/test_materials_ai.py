import threading

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

import app.config as config
from app import analysis, openai_client
from app.database import SessionLocal
from app.main import app
from app.models.material import Material
from app.models.user import User
from tests.conftest import signup_payload
from tests.test_materials_upload import jpeg, mp4, png, stored_files, upload
from tests.test_openai_client import FakeClient, ok, status_error
from tests.test_video_frames import make_video

SECRET = "sk-SECRET-KEY-123456789"
NOT_FOUND = {"detail": "자료를 찾을 수 없습니다.", "field": None}


@pytest.fixture
def ai_on(monkeypatch):
    """키가 있는 상태 + 가짜 OpenAI. 예약된 분석은 즉시(같은 스레드에서) 실행해 결과를 바로 확인합니다."""
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))
    client = FakeClient(ok(text="주제\n- 핵심 1\n- 핵심 2"))
    monkeypatch.setattr(openai_client, "create_client", lambda: client)
    monkeypatch.setattr(analysis, "submit", lambda material_id: analysis.run_analysis(material_id))
    return client


@pytest.fixture
def queued(monkeypatch):
    """분석을 예약만 하고 실행하지 않는 상태. 업로드 응답이 분석을 기다리지 않는지 확인합니다."""
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))
    ids = []
    monkeypatch.setattr(analysis, "submit", lambda material_id: ids.append(material_id))
    return ids


def row(material_id) -> Material:
    with SessionLocal() as db:
        return db.get(Material, material_id)


def items(client):
    return {item["id"]: item for item in client.get("/api/materials").json()["items"]}


@pytest.fixture
def two_users(make_client):
    clients = []
    for email, nickname in (("a@example.com", "사용자A"), ("b@example.com", "사용자B")):
        c = make_client()
        payload = signup_payload(email=email, nickname=nickname)
        assert c.post("/api/auth/signup", json=payload).status_code == 201
        assert c.post("/api/auth/login", json={"email": email, "password": payload["password"]}).status_code == 200
        clients.append(c)
    return clients


# ---------- 업로드 → 자동 분석 ----------


def test_키가_없으면_업로드는_그대로_되고_분석은_안_한다(logged_in):
    response = upload(logged_in)
    assert response.status_code == 201
    body = response.json()
    assert (body["analysis_status"], body["summary"], body["analysis_message"]) == ("skipped", None, None)
    assert logged_in.get("/api/materials").json()["ai_enabled"] is False


def test_키가_있으면_업로드_직후_분석이_예약되고_응답은_기다리지_않는다(logged_in, queued):
    response = upload(logged_in)
    assert response.status_code == 201
    assert response.json()["analysis_status"] == "pending"
    assert response.json()["summary"] is None
    assert queued == [response.json()["id"]]  # 분석이 예약됨 (아직 실행 전)
    assert row(response.json()["id"]).analysis_status == "pending"


def test_분석이_끝나면_목록에_요약이_나타난다(logged_in, ai_on):
    created = upload(logged_in, memo="수업 캡처").json()
    shown = items(logged_in)[created["id"]]
    assert shown["analysis_status"] == "done"
    assert shown["summary"] == "주제\n- 핵심 1\n- 핵심 2"
    assert shown["analysis_message"] is None
    assert logged_in.get("/api/materials").json()["ai_enabled"] is True
    saved = row(created["id"])
    assert (saved.analysis_model, saved.analysis_error) == ("gpt-6-luna", None)
    assert saved.analyzed_at is not None
    # OpenAI로 간 내용: 올린 이미지와 참고 정보
    content = ai_on.last["input"][0]["content"]
    assert "제목: REST API 정리" in content[0]["text"] and "메모: 수업 캡처" in content[0]["text"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "off", "no", " false "])
def test_AI_요약을_끄고_올리면_분석하지_않는다(logged_in, ai_on, value):
    created = upload(logged_in, ai_summary=value).json()
    assert created["analysis_status"] == "skipped"
    assert ai_on.responses.calls == []


@pytest.mark.parametrize("value", ["true", "1", "on", "", "아무거나"])
def test_AI_요약_값이_꺼짐이_아니면_분석한다(logged_in, ai_on, value):
    created = upload(logged_in, ai_summary=value).json()
    assert items(logged_in)[created["id"]]["analysis_status"] == "done"
    assert len(ai_on.responses.calls) == 1


def test_AI_요약_값을_보내지_않아도_분석한다_예전_화면과_호환(logged_in, ai_on):
    created = upload(logged_in).json()  # ai_summary 필드 없음
    assert items(logged_in)[created["id"]]["analysis_status"] == "done"


def test_영상을_올리면_장면을_뽑아_요약한다(logged_in, ai_on, tmp_path):
    video = make_video(tmp_path / "v.mp4", seconds=3)
    created = upload(logged_in, files={"file": ("demo.mp4", video.read_bytes(), "video/mp4")}).json()

    shown = items(logged_in)[created["id"]]
    assert (shown["kind"], shown["analysis_status"]) == ("video", "done")
    content = ai_on.last["input"][0]["content"]
    assert "영상 (장면" in content[0]["text"] and len(content) - 1 >= 2
    assert all(part["image_url"].startswith("data:image/jpeg;base64,") for part in content[1:])


def test_AI가_실패해도_자료와_파일은_그대로_남는다(logged_in, monkeypatch, isolated_uploads):
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))
    monkeypatch.setattr(openai_client, "create_client", lambda: FakeClient(status_error(openai.RateLimitError, 429)))
    monkeypatch.setattr(analysis, "submit", lambda material_id: analysis.run_analysis(material_id))

    response = upload(logged_in)
    assert response.status_code == 201  # 업로드는 성공
    shown = items(logged_in)[response.json()["id"]]
    assert shown["analysis_status"] == "failed"
    assert shown["analysis_message"] == openai_client.message_for("rate_limit")
    assert shown["summary"] is None
    assert len(stored_files(isolated_uploads)) == 1  # 파일도 그대로
    assert logged_in.get(f"/api/materials/{shown['id']}/file").status_code == 200


def test_예약에_실패해도_업로드는_성공하고_실패로_표시된다(logged_in, monkeypatch):
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))

    def broken(material_id):
        raise RuntimeError("실행기 오류")

    monkeypatch.setattr(analysis, "submit", broken)
    response = upload(logged_in)
    assert response.status_code == 201
    body = response.json()
    assert (body["analysis_status"], body["analysis_message"]) == ("failed", openai_client.message_for("unknown"))


def test_저장_자체가_실패하면_분석을_예약하지_않는다(logged_in, queued, db, isolated_uploads):
    response = upload(logged_in, title="")  # 제목 오류로 저장 실패
    assert response.status_code == 422
    assert queued == []
    assert db.scalars(select(Material)).all() == []


def test_허용하지_않는_파일은_분석을_예약하지_않는다(logged_in, queued):
    response = upload(logged_in, files={"file": ("a.gif", b"GIF89a", "image/gif")})
    assert response.status_code == 415
    assert queued == []


# ---------- 응답 모양 ----------


def test_분석_내부_정보는_응답에_없다(logged_in, ai_on):
    created = upload(logged_in).json()
    for body in (created, items(logged_in)[created["id"]]):
        assert not {"analysis_error", "analysis_model", "analyzed_at", "storage_name", "user_id"} & set(body)


def test_요약은_올린_사람의_목록에만_나온다(two_users, ai_on):
    a, b = two_users
    created = upload(a, title="A의 자료").json()
    assert items(a)[created["id"]]["summary"]
    assert b.get("/api/materials").json()["items"] == []


# ---------- 다시 분석 ----------


def make_failed(client, ai_on, monkeypatch):
    """분석에 실패한 자료 한 건을 만듭니다."""
    failing = FakeClient(openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses")))
    monkeypatch.setattr(openai_client, "create_client", lambda: failing)
    created = upload(client).json()
    assert items(client)[created["id"]]["analysis_status"] == "failed"
    monkeypatch.setattr(openai_client, "create_client", lambda: ai_on)  # 이제 정상 응답
    return created["id"]


def test_실패한_자료는_다시_분석할_수_있다(logged_in, ai_on, monkeypatch):
    material_id = make_failed(logged_in, ai_on, monkeypatch)
    monkeypatch.setattr(analysis, "submit", lambda mid: None)  # 먼저 예약만 해서 pending 응답을 본다

    response = logged_in.post(f"/api/materials/{material_id}/analyze")
    assert response.status_code == 202
    assert response.json()["analysis_status"] == "pending"
    assert response.json()["analysis_message"] is None  # 이전 실패 문구가 남지 않음
    assert row(material_id).analysis_error is None

    analysis.run_analysis(material_id)  # 예약된 분석이 실행되면
    assert items(logged_in)[material_id]["analysis_status"] == "done"
    assert items(logged_in)[material_id]["summary"]


def test_분석하지_않은_자료도_요약을_만들_수_있다(logged_in, ai_on):
    created = upload(logged_in, ai_summary="false").json()
    assert created["analysis_status"] == "skipped"
    response = logged_in.post(f"/api/materials/{created['id']}/analyze")
    assert response.status_code == 202
    assert items(logged_in)[created["id"]]["analysis_status"] == "done"


def test_분석_중이거나_완료된_자료는_409다(logged_in, ai_on, queued):
    pending = upload(logged_in).json()  # queued: 분석 중 상태로 남음
    r = logged_in.post(f"/api/materials/{pending['id']}/analyze")
    assert (r.status_code, r.json()) == (409, {"detail": "이미 분석 중이에요.", "field": None})
    assert row(pending["id"]).analysis_status == "pending"
    assert queued == [pending["id"]]  # 두 번째 예약이 생기지 않음

    analysis.run_analysis(pending["id"])  # 완료됨
    r = logged_in.post(f"/api/materials/{pending['id']}/analyze")
    assert (r.status_code, r.json()) == (409, {"detail": "이미 요약이 있어요.", "field": None})
    assert len(ai_on.responses.calls) == 1  # 다시 부르지 않음


def test_남의_자료와_없는_자료는_본문까지_같은_404다(two_users, ai_on):
    a, b = two_users
    created = upload(a).json()
    others = b.post(f"/api/materials/{created['id']}/analyze")
    missing = b.post("/api/materials/999999/analyze")
    assert others.status_code == missing.status_code == 404
    assert others.json() == missing.json() == NOT_FOUND
    assert others.content == missing.content
    assert len(ai_on.responses.calls) == 1  # 남의 요청으로 분석이 다시 일어나지 않음


def test_AI가_꺼져_있어도_남의_자료는_404고_내_자료는_503이다(two_users, monkeypatch):
    a, b = two_users
    created = upload(a).json()  # 키 없음 → skipped
    assert b.post(f"/api/materials/{created['id']}/analyze").json() == NOT_FOUND  # 존재 여부를 알려주지 않음
    mine = a.post(f"/api/materials/{created['id']}/analyze")
    assert (mine.status_code, mine.json()) == (503, {"detail": "AI 요약을 사용할 수 없어요.", "field": None})
    assert row(created["id"]).analysis_status == "skipped"


def test_로그인하지_않으면_다시_분석할_수_없다(logged_in, ai_on):
    created = upload(logged_in).json()
    with TestClient(app) as anonymous:
        response = anonymous.post(f"/api/materials/{created['id']}/analyze")
    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요합니다.", "field": None}


def test_올바르지_않은_번호는_거절한다(logged_in, ai_on):
    assert logged_in.post("/api/materials/abc/analyze").status_code == 422


def test_같은_자료에_동시에_분석을_요청해도_한_번만_시작된다(logged_in, ai_on, queued):
    created = upload(logged_in, ai_summary="false").json()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id))
    queued.clear()
    results, barrier = [], threading.Barrier(5)

    def worker():
        c = TestClient(app)
        c.cookies = logged_in.cookies
        barrier.wait()
        results.append(c.post(f"/api/materials/{created['id']}/analyze").status_code)
        c.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [202, 409, 409, 409, 409]
    assert queued == [created["id"]]  # 예약은 한 번뿐
    assert user_id


def test_분석_중에_삭제하면_오류_없이_결과를_버린다(logged_in, ai_on, queued):
    created = upload(logged_in).json()  # pending, 아직 실행 전
    assert logged_in.delete(f"/api/materials/{created['id']}").status_code == 204

    analysis.run_analysis(created["id"])  # 예약된 분석이 뒤늦게 실행됨

    assert ai_on.responses.calls == []  # 없는 자료이므로 OpenAI를 부르지 않음
    assert logged_in.get("/api/materials").json()["items"] == []


# ---------- 서버 시작 시 정리 ----------


def test_서버가_켜질_때_남아_있던_진행_중은_중단으로_정리된다(logged_in, queued, db):
    pending = upload(logged_in).json()  # pending으로 남음 (서버가 이전에 죽은 상황)
    skipped = upload(logged_in, ai_summary="false").json()
    assert row(pending["id"]).analysis_status == "pending"

    with TestClient(app):  # 시작(lifespan)이 실행됨
        pass

    saved = row(pending["id"])
    assert (saved.analysis_status, saved.analysis_error) == ("failed", "interrupted")
    assert row(skipped["id"]).analysis_status == "skipped"
    shown = items(logged_in)[pending["id"]]
    assert "다시 시작" in shown["analysis_message"]


def test_정리에_실패해도_서버는_시작된다(monkeypatch):
    def boom():
        raise RuntimeError("데이터베이스 오류")

    monkeypatch.setattr(analysis, "recover_interrupted", boom)
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


# ---------- 비밀 ----------


def test_모든_경우에_응답과_기록에_키가_없다(logged_in, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))
    monkeypatch.setattr(analysis, "submit", lambda mid: analysis.run_analysis(mid))
    texts = []
    for outcome in (ok(), status_error(openai.AuthenticationError, 401), RuntimeError(f"오류 {SECRET}")):
        monkeypatch.setattr(openai_client, "create_client", lambda outcome=outcome: FakeClient(outcome))
        created = upload(logged_in, title="개인적인 제목", memo="개인적인 메모").json()
        texts.append(str(created))
        texts.append(str(logged_in.get("/api/materials").json()))
    assert SECRET not in "".join(texts) and "Incorrect API key" not in "".join(texts)
    assert SECRET not in caplog.text and "Incorrect API key" not in caplog.text
    assert "개인적인" not in caplog.text
