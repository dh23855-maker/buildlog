import logging
import threading
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx2
import openai
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update

import app.config as config
from app import analysis, openai_client
from app.database import SessionLocal, engine
from app.errors import ApiError
from app.models.ai_usage import AiUsage
from app.models.material import Material
from app.models.user import User
from app.schemas.material import MaterialResponse
from app.security import hash_password
from app import video_frames
from tests.test_openai_client import FakeClient, ok, status_error
from tests.test_video_frames import make_video

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
SECRET = "sk-SECRET-KEY-123456789"


@pytest.fixture(autouse=True)
def ai_on(monkeypatch):
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))


def use_client(monkeypatch, client):
    monkeypatch.setattr(openai_client, "create_client", lambda: client)
    return client


def make_user(email="a@example.com", nickname="사용자A") -> int:
    with SessionLocal() as db:
        user = User(email=email, password_hash=hash_password("password123"), nickname=nickname)
        db.add(user)
        db.commit()
        return user.id


def make_material(user_id, uploads, *, status="pending", kind="image", with_file=True, content=PNG, **overrides) -> int:
    ext = "mp4" if kind == "video" else "png"
    storage_name = f"{uuid.uuid4().hex}.{ext}"
    if with_file:
        uploads.mkdir(parents=True, exist_ok=True)
        (uploads / storage_name).write_bytes(content)
    values = {
        "user_id": user_id,
        "title": "REST API 정리",
        "memo": "수업 캡처",
        "kind": kind,
        "original_filename": f"a.{ext}",
        "content_type": "video/mp4" if kind == "video" else "image/png",
        "size_bytes": max(len(content), 1),
        "storage_name": storage_name,
        "analysis_status": status,
    }
    values.update(overrides)
    with SessionLocal() as db:
        material = Material(**values)
        db.add(material)
        db.commit()
        return material.id


def get_material(material_id) -> Material | None:
    with SessionLocal() as db:
        return db.get(Material, material_id)


def usage(user_id) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.coalesce(func.sum(AiUsage.count), 0)).where(AiUsage.user_id == user_id))


# ---------- 상태 정하기 ----------


@pytest.mark.parametrize(
    "key, want, expected",
    [("sk-x", True, "pending"), ("sk-x", False, "skipped"), ("", True, "skipped"), ("", False, "skipped")],
)
def test_처음_상태는_키와_사용자_선택으로_정한다(monkeypatch, key, want, expected):
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(key))
    assert analysis.decide_initial_status(want) == expected


# ---------- 성공 ----------


def test_이미지를_분석하면_요약과_모델과_시각이_저장된다(monkeypatch, isolated_uploads):
    client = use_client(monkeypatch, FakeClient(ok(text="주제\n- 핵심")))
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads)

    analysis.run_analysis(material_id)

    saved = get_material(material_id)
    assert saved.analysis_status == "done"
    assert saved.summary == "주제\n- 핵심"
    assert saved.analysis_model == "gpt-6-luna"
    assert saved.analysis_error is None
    assert saved.analyzed_at is not None
    assert usage(user_id) == 1

    # OpenAI로 간 내용: 올린 파일 그대로, 제목·메모는 참고 정보로
    content = client.last["input"][0]["content"]
    assert "제목: REST API 정리" in content[0]["text"] and "메모: 수업 캡처" in content[0]["text"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_진행_중이_아닌_자료는_분석하지_않는다(monkeypatch, isolated_uploads):
    client = use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    ids = {s: make_material(user_id, isolated_uploads, status=s) for s in ("skipped", "done", "failed")}

    for material_id in ids.values():
        analysis.run_analysis(material_id)

    assert client.responses.calls == []
    assert usage(user_id) == 0
    assert {s: get_material(i).analysis_status for s, i in ids.items()} == {s: s for s in ids}


def test_없는_자료는_조용히_넘어간다(monkeypatch):
    client = use_client(monkeypatch, FakeClient(ok()))
    analysis.run_analysis(999999)
    assert client.responses.calls == []


# ---------- 실패 ----------


@pytest.mark.parametrize(
    "error, code",
    [
        (status_error(openai.AuthenticationError, 401), "auth"),
        (status_error(openai.RateLimitError, 429), "rate_limit"),
        (status_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"}), "billing"),
        (openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses")), "timeout"),
        (status_error(openai.NotFoundError, 404), "model"),
        (status_error(openai.InternalServerError, 500), "server"),
    ],
)
def test_OpenAI_오류는_실패와_코드로_저장되고_예외는_밖으로_나오지_않는다(monkeypatch, isolated_uploads, error, code):
    use_client(monkeypatch, FakeClient(error))
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads)

    analysis.run_analysis(material_id)  # 예외 없이 끝남

    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error) == ("failed", code)
    assert saved.summary is None
    assert saved.analyzed_at is not None
    assert saved.analysis_message == openai_client.message_for(code)
    # OpenAI를 이미 불렀으므로 한도는 사용됨 (비용이 발생했을 수 있기 때문)
    assert usage(user_id) == 1


def test_예상하지_못한_오류도_실패로_저장하고_밖으로_던지지_않는다(monkeypatch, isolated_uploads, caplog):
    use_client(monkeypatch, FakeClient(RuntimeError(f"내부 오류 {SECRET}")))
    material_id = make_material(make_user(), isolated_uploads)

    analysis.run_analysis(material_id)

    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error) == ("failed", "unknown")
    assert saved.analysis_message == openai_client.message_for("unknown")


def test_파일이_없으면_실패하고_OpenAI를_부르지_않고_한도도_쓰지_않는다(monkeypatch, isolated_uploads):
    client = use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads, with_file=False)

    analysis.run_analysis(material_id)

    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error) == ("failed", "file_missing")
    assert client.responses.calls == []
    assert usage(user_id) == 0


def test_저장_이름이_이상한_자료는_폴더_밖_파일을_읽지_않는다(monkeypatch, isolated_uploads, tmp_path):
    client = use_client(monkeypatch, FakeClient(ok()))
    (tmp_path / "secret.png").write_bytes(PNG)
    material_id = make_material(make_user(), isolated_uploads, with_file=False, storage_name="../../secret.png")

    analysis.run_analysis(material_id)

    assert get_material(material_id).analysis_error == "file_missing"
    assert client.responses.calls == []


def test_영상이_아닌_내용의_mp4는_frames로_실패하고_한도를_쓰지_않는다(monkeypatch, isolated_uploads):
    client = use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads, kind="video")  # 내용은 PNG 바이트

    analysis.run_analysis(material_id)

    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error) == ("failed", "frames")
    assert saved.analysis_message == openai_client.message_for("frames")
    assert client.responses.calls == [] and usage(user_id) == 0


def test_영상은_장면_여러_장으로_바꿔_한_번에_요약한다(monkeypatch, isolated_uploads, tmp_path):
    client = use_client(monkeypatch, FakeClient(ok(text="영상 요약")))
    user_id = make_user()
    video = make_video(tmp_path / "v.mp4", seconds=4)
    material_id = make_material(user_id, isolated_uploads, kind="video", content=video.read_bytes())

    analysis.run_analysis(material_id)

    saved = get_material(material_id)
    assert (saved.analysis_status, saved.summary, saved.analysis_model) == ("done", "영상 요약", "gpt-6-luna")
    content = client.last["input"][0]["content"]
    assert "영상 (장면 8장, 시간순)" in content[0]["text"]
    frames = content[1:]
    assert len(frames) == 8 and len(client.responses.calls) == 1  # 장면마다 따로 부르지 않고 한 번에
    assert all(f["image_url"].startswith("data:image/jpeg;base64,") and f["detail"] == "auto" for f in frames)
    assert usage(user_id) == 1  # 영상 한 건은 한도 한 번


def test_gpt_4o_mini로_바꾸면_영상_장면을_low로_보낸다(monkeypatch, isolated_uploads, tmp_path):
    monkeypatch.setattr(config.settings, "openai_model", "gpt-4o-mini")
    client = use_client(monkeypatch, FakeClient(ok()))
    video = make_video(tmp_path / "v.mp4", seconds=2)
    material_id = make_material(make_user(), isolated_uploads, kind="video", content=video.read_bytes())

    analysis.run_analysis(material_id)

    assert get_material(material_id).analysis_model == "gpt-4o-mini"
    assert {f["detail"] for f in client.last["input"][0]["content"][1:]} == {"low"}
    assert "reasoning" not in client.last


def test_장면_추출이_시간_초과되면_frames로_실패하고_한도를_쓰지_않는다(monkeypatch, isolated_uploads, tmp_path):
    client = use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    video = make_video(tmp_path / "v.mp4", seconds=2)
    material_id = make_material(user_id, isolated_uploads, kind="video", content=video.read_bytes())

    def slow(*args, **kwargs):
        raise video_frames.subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

    monkeypatch.setattr(video_frames.subprocess, "run", slow)
    analysis.run_analysis(material_id)

    assert get_material(material_id).analysis_error == "frames"
    assert client.responses.calls == [] and usage(user_id) == 0


def test_장면_추출_중_예상하지_못한_오류도_실패로_저장한다(monkeypatch, isolated_uploads, tmp_path):
    use_client(monkeypatch, FakeClient(ok()))
    video = make_video(tmp_path / "v.mp4", seconds=2)
    material_id = make_material(make_user(), isolated_uploads, kind="video", content=video.read_bytes())

    def boom(path):
        raise MemoryError("메모리 부족")

    monkeypatch.setattr(video_frames, "extract_frames", boom)
    analysis.run_analysis(material_id)  # 서버로 예외가 번지지 않음

    assert get_material(material_id).analysis_error == "unknown"


# ---------- 하루 한도 ----------


def test_한도까지는_성공하고_넘으면_quota로_실패한다(monkeypatch, isolated_uploads):
    monkeypatch.setattr(config.settings, "ai_daily_limit", 2)
    client = use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    ids = [make_material(user_id, isolated_uploads) for _ in range(3)]

    for material_id in ids:
        analysis.run_analysis(material_id)

    statuses = [get_material(i).analysis_status for i in ids]
    assert statuses == ["done", "done", "failed"]
    over = get_material(ids[2])
    assert over.analysis_error == "quota"
    assert "2회" in over.analysis_message
    assert len(client.responses.calls) == 2  # 한도를 넘은 건은 OpenAI를 부르지 않음
    assert usage(user_id) == 2


def test_자료를_지워도_횟수는_돌아오지_않는다(monkeypatch, isolated_uploads):
    monkeypatch.setattr(config.settings, "ai_daily_limit", 1)
    use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    first = make_material(user_id, isolated_uploads)
    analysis.run_analysis(first)
    assert get_material(first).analysis_status == "done"

    with SessionLocal() as db:  # 자료를 지워 한도를 되돌리려는 시도
        db.execute(delete(Material).where(Material.id == first))
        db.commit()

    second = make_material(user_id, isolated_uploads)
    analysis.run_analysis(second)
    assert get_material(second).analysis_error == "quota"
    assert usage(user_id) == 1


def test_사용자마다_따로_센다(monkeypatch, isolated_uploads):
    monkeypatch.setattr(config.settings, "ai_daily_limit", 1)
    use_client(monkeypatch, FakeClient(ok()))
    a, b = make_user("a@example.com", "사용자A"), make_user("b@example.com", "사용자B")
    ma, mb = make_material(a, isolated_uploads), make_material(b, isolated_uploads)
    analysis.run_analysis(ma)
    analysis.run_analysis(mb)
    assert get_material(ma).analysis_status == get_material(mb).analysis_status == "done"


def test_날짜가_바뀌면_횟수가_새로_시작한다(monkeypatch, isolated_uploads):
    monkeypatch.setattr(config.settings, "ai_daily_limit", 1)
    use_client(monkeypatch, FakeClient(ok()))
    user_id = make_user()
    today = date(2026, 10, 27)
    monkeypatch.setattr(analysis, "today_kst", lambda: today)
    first, second = make_material(user_id, isolated_uploads), make_material(user_id, isolated_uploads)
    analysis.run_analysis(first)
    analysis.run_analysis(second)
    assert [get_material(first).analysis_status, get_material(second).analysis_error] == ["done", "quota"]

    monkeypatch.setattr(analysis, "today_kst", lambda: today + timedelta(days=1))
    third = make_material(user_id, isolated_uploads)
    analysis.run_analysis(third)
    assert get_material(third).analysis_status == "done"
    with SessionLocal() as db:
        assert [(r.day, r.count) for r in db.scalars(select(AiUsage).order_by(AiUsage.day))] == [
            (today, 1),
            (today + timedelta(days=1), 1),
        ]


def test_하루는_한국_날짜_기준이다():
    assert analysis.kst_day(datetime(2026, 10, 27, 14, 59, tzinfo=UTC)) == date(2026, 10, 27)  # 한국 23:59
    assert analysis.kst_day(datetime(2026, 10, 27, 15, 0, tzinfo=UTC)) == date(2026, 10, 28)  # 한국 00:00


def test_동시에_요청해도_한도를_넘지_않는다():
    limit = 5
    original = config.settings.ai_daily_limit
    config.settings.ai_daily_limit = limit
    try:
        user_id = make_user()
        results, barrier = [], threading.Barrier(12)

        def worker():
            with SessionLocal() as db:
                barrier.wait()
                results.append(analysis.reserve_quota(db, user_id))

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        config.settings.ai_daily_limit = original

    assert len(results) == 12
    assert results.count(True) == limit  # 정확히 한도만큼만 통과
    assert usage(user_id) == limit


# ---------- 분석 도중 상황 변화 ----------


class HookClient(FakeClient):
    """OpenAI 호출 도중에 다른 일이 벌어지는 상황을 흉내 냅니다."""

    def __init__(self, outcome, hook):
        super().__init__(outcome)
        original = self.responses.create

        def create(**kwargs):
            hook()
            return original(**kwargs)

        self.responses.create = create


def test_분석_중에_자료가_삭제되면_결과를_버리고_오류_없이_끝난다(monkeypatch, isolated_uploads):
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads)

    def delete_now():
        with SessionLocal() as db:
            db.execute(delete(Material).where(Material.id == material_id))
            db.commit()

    use_client(monkeypatch, HookClient(ok(), delete_now))
    analysis.run_analysis(material_id)  # 예외 없음

    assert get_material(material_id) is None
    assert usage(user_id) == 1  # OpenAI는 이미 불렀으므로 한도는 사용됨


def test_분석_중에_상태가_바뀌면_결과를_덮어쓰지_않는다(monkeypatch, isolated_uploads):
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads)

    def interrupt_now():  # 예: 서버 재시작 정리가 먼저 실패로 바꾼 경우
        analysis_state = analysis.recover_interrupted()
        assert analysis_state == 1

    use_client(monkeypatch, HookClient(ok(text="늦게 온 요약"), interrupt_now))
    analysis.run_analysis(material_id)

    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error, saved.summary) == ("failed", "interrupted", None)


def test_OpenAI를_기다리는_동안_데이터베이스_연결을_잡고_있지_않다(monkeypatch, isolated_uploads):
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads)
    seen = {}

    def check_pool():
        seen["checked_out"] = engine.pool.checkedout()

    use_client(monkeypatch, HookClient(ok(), check_pool))
    analysis.run_analysis(material_id)

    assert seen["checked_out"] == 0  # 호출하는 동안 열려 있는 DB 연결이 없음
    assert get_material(material_id).analysis_status == "done"


# ---------- 다시 분석 요청 ----------


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_실패했거나_분석하지_않은_자료는_다시_분석_대기가_된다(isolated_uploads, status):
    user_id = make_user()
    material_id = make_material(
        user_id, isolated_uploads, status=status, analysis_error="timeout" if status == "failed" else None,
        analyzed_at=datetime.now(UTC) if status == "failed" else None,
    )
    with SessionLocal() as db:
        material = analysis.request_reanalysis(db, user_id, material_id)
        assert material.analysis_status == "pending"
    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error, saved.analyzed_at) == ("pending", None, None)


@pytest.mark.parametrize("status, message", [("pending", "이미 분석 중이에요."), ("done", "이미 요약이 있어요.")])
def test_분석_중이거나_완료된_자료는_다시_분석할_수_없다(isolated_uploads, status, message):
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads, status=status, summary="요약" if status == "done" else None)
    with SessionLocal() as db, pytest.raises(ApiError) as raised:
        analysis.request_reanalysis(db, user_id, material_id)
    assert (raised.value.status_code, raised.value.message) == (409, message)
    assert get_material(material_id).analysis_status == status


def test_남의_자료와_없는_자료는_같은_404다(isolated_uploads):
    a, b = make_user("a@example.com", "사용자A"), make_user("b@example.com", "사용자B")
    material_id = make_material(a, isolated_uploads, status="failed")
    errors = []
    for target in (material_id, 999999):
        with SessionLocal() as db, pytest.raises(ApiError) as raised:
            analysis.request_reanalysis(db, b, target)
        errors.append((raised.value.status_code, raised.value.message, raised.value.field))
    assert errors[0] == errors[1] == (404, "자료를 찾을 수 없습니다.", None)
    assert get_material(material_id).analysis_status == "failed"  # 남의 자료는 바뀌지 않음


def test_같은_자료를_동시에_다시_분석해도_한_번만_받아들인다(isolated_uploads):
    user_id = make_user()
    material_id = make_material(user_id, isolated_uploads, status="failed")
    outcomes, barrier = [], threading.Barrier(6)

    def worker():
        with SessionLocal() as db:
            barrier.wait()
            try:
                analysis.request_reanalysis(db, user_id, material_id)
                outcomes.append("ok")
            except ApiError as error:
                outcomes.append(error.status_code)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("ok") == 1
    assert outcomes.count(409) == 5


# ---------- 시작 시 정리 ----------


def test_시작할_때_남아_있던_진행_중은_중단으로_바뀌고_나머지는_그대로다(isolated_uploads):
    user_id = make_user()
    pending = [make_material(user_id, isolated_uploads, status="pending") for _ in range(2)]
    others = {s: make_material(user_id, isolated_uploads, status=s) for s in ("skipped", "done", "failed")}

    assert analysis.recover_interrupted() == 2

    for material_id in pending:
        saved = get_material(material_id)
        assert (saved.analysis_status, saved.analysis_error) == ("failed", "interrupted")
        assert "다시 시작" in saved.analysis_message
    assert {s: get_material(i).analysis_status for s, i in others.items()} == {s: s for s in others}
    assert analysis.recover_interrupted() == 0  # 다시 실행해도 안전


# ---------- 실행기 ----------


def test_예약하면_별도_스레드에서_분석하고_동시_실행은_2개로_제한한다(monkeypatch):
    done, names = threading.Event(), []

    def fake_run(material_id):
        names.append((material_id, threading.current_thread().name))
        done.set()

    monkeypatch.setattr(analysis, "run_analysis", fake_run)
    monkeypatch.setattr(analysis, "_executor", None)
    analysis.submit(42)
    assert done.wait(5)
    assert names[0][0] == 42
    assert names[0][1].startswith("ai-analysis") and names[0][1] != threading.current_thread().name
    assert analysis._get_executor()._max_workers == config.AI_WORKERS == 2
    analysis._executor.shutdown(wait=True)
    monkeypatch.setattr(analysis, "_executor", None)


def test_예약에_실패하면_자료를_실패로_표시한다(monkeypatch, isolated_uploads):
    material_id = make_material(make_user(), isolated_uploads)

    def broken(_):
        raise RuntimeError("실행기 오류")

    monkeypatch.setattr(analysis, "submit", broken)
    assert analysis.submit_or_fail(material_id) is False
    saved = get_material(material_id)
    assert (saved.analysis_status, saved.analysis_error) == ("failed", "unknown")


# ---------- 응답 문구·기록 ----------


def test_실패한_자료만_사용자_문구를_가진다(isolated_uploads):
    user_id = make_user()
    failed = make_material(user_id, isolated_uploads, status="failed", analysis_error="rate_limit")
    done = make_material(user_id, isolated_uploads, status="done", summary="요약")
    assert MaterialResponse.model_validate(get_material(failed)).analysis_message == openai_client.message_for("rate_limit")
    assert MaterialResponse.model_validate(get_material(done)).analysis_message is None
    # 알 수 없는 코드도 일반 안내로 보여 준다
    unknown = make_material(user_id, isolated_uploads, status="failed", analysis_error="something")
    assert MaterialResponse.model_validate(get_material(unknown)).analysis_message == openai_client.message_for("unknown")


def test_기록에_제목_메모_요약_키가_남지_않는다(monkeypatch, isolated_uploads, caplog):
    caplog.set_level(logging.DEBUG)
    use_client(monkeypatch, FakeClient(ok(text="비밀 요약 내용")))
    user_id = make_user()
    ok_id = make_material(user_id, isolated_uploads, title="개인적인 제목", memo="개인적인 메모")
    analysis.run_analysis(ok_id)
    use_client(monkeypatch, FakeClient(status_error(openai.AuthenticationError, 401)))
    bad_id = make_material(user_id, isolated_uploads, title="개인적인 제목2", memo="개인적인 메모2")
    analysis.run_analysis(bad_id)

    for secret in ("개인적인", "비밀 요약 내용", SECRET, "Incorrect API key"):
        assert secret not in caplog.text
    assert f"material={ok_id}" in caplog.text
