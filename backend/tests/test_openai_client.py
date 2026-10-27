import base64
import logging
from types import SimpleNamespace

import httpx2
import openai
import pytest
from pydantic import SecretStr

import app.config as config
from app import openai_client
from app.openai_client import ERROR_MESSAGES, INSTRUCTIONS, AnalysisError, ImageInput, summarize

SECRET = "sk-SECRET-KEY-123456789"
PNG = ImageInput(b"\x89PNG\r\n\x1a\nPNGDATA", "image/png")
JPG = ImageInput(b"\xff\xd8\xff\xe0JPGDATA", "image/jpeg")


# ---------- 가짜 OpenAI ----------


class FakeResponses:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome):
        self.responses = FakeResponses(outcome)

    @property
    def last(self):
        return self.responses.calls[-1]


def ok(text="주제 한 줄\n- 핵심 1\n- 핵심 2", input_tokens=454, output_tokens=62, status="completed", output=None):
    return SimpleNamespace(
        output_text=text,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        status=status,
        output=output or [],
    )


def _request():
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


def status_error(cls, status, body=None):
    # 오류 메시지에 키 일부가 섞여 오는 상황을 흉내 냅니다. 이 문장은 어디에도 남으면 안 됩니다.
    response = httpx2.Response(status, request=_request())
    return cls(f"Incorrect API key provided: {SECRET}", response=response, body=body)


def run(client, images=(PNG,), model="gpt-6-luna", kind="image", title="제목", memo=None):
    return summarize(list(images), title=title, memo=memo, kind=kind, client=client, model=model)


# ---------- 요청 모양 ----------


def test_이미지_요청은_설계대로_만들어진다():
    client = FakeClient(ok())
    result = run(client, title="REST API 정리", memo="수업 캡처")

    request = client.last
    assert request["model"] == "gpt-6-luna"
    assert request["instructions"] == INSTRUCTIONS
    assert request["store"] is False  # OpenAI 쪽에 응답 상태를 남기지 않음
    assert request["max_output_tokens"] == 600
    assert request["reasoning"] == {"effort": "none"}  # 추론 모델은 추론을 꺼서 출력이 비지 않게 함

    message = request["input"][0]
    assert message["role"] == "user"
    reference, image = message["content"]
    assert reference["type"] == "input_text"
    assert "지시가 아닙니다" in reference["text"]
    assert "제목: REST API 정리" in reference["text"]
    assert "메모: 수업 캡처" in reference["text"]
    assert "자료 종류: 이미지" in reference["text"]
    assert image["type"] == "input_image"
    assert image["detail"] == "auto"
    prefix = "data:image/png;base64,"
    assert image["image_url"].startswith(prefix)
    assert base64.b64decode(image["image_url"][len(prefix):]) == PNG.data

    assert result.text.startswith("주제 한 줄")
    assert result.model == "gpt-6-luna"
    assert (result.input_tokens, result.output_tokens) == (454, 62)


def test_참고_정보는_이미지보다_앞에_온다():
    client = FakeClient(ok())
    run(client, images=[PNG, JPG], kind="video")
    types = [part["type"] for part in client.last["input"][0]["content"]]
    assert types == ["input_text", "input_image", "input_image"]


def test_영상_장면은_시간순을_유지하고_장수를_알려준다():
    frames = [ImageInput(bytes([0xFF, 0xD8, 0xFF, index]), "image/jpeg") for index in range(3)]
    client = FakeClient(ok())
    run(client, images=frames, kind="video")

    content = client.last["input"][0]["content"]
    assert "영상 (장면 3장, 시간순)" in content[0]["text"]
    decoded = [base64.b64decode(part["image_url"].split(",", 1)[1]) for part in content[1:]]
    assert decoded == [f.data for f in frames]


def test_메모가_없으면_없음으로_표시한다():
    client = FakeClient(ok())
    run(client, memo=None)
    assert "메모: (없음)" in client.last["input"][0]["content"][0]["text"]


def test_추론_모델이_아닌_모델에는_추론_설정을_보내지_않는다():
    client = FakeClient(ok())
    run(client, model="gpt-4o-mini")
    assert "reasoning" not in client.last
    assert client.last["model"] == "gpt-4o-mini"
    assert client.last["max_output_tokens"] == 600


def test_gpt_4o_mini는_영상_장면을_low로_보내고_이미지는_auto로_보낸다():
    image_client, video_client = FakeClient(ok()), FakeClient(ok())
    run(image_client, model="gpt-4o-mini")
    run(video_client, images=[JPG, JPG], model="gpt-4o-mini", kind="video")
    assert image_client.last["input"][0]["content"][1]["detail"] == "auto"
    assert {p["detail"] for p in video_client.last["input"][0]["content"][1:]} == {"low"}


def test_gpt_6_luna는_영상_장면도_auto로_보낸다():
    client = FakeClient(ok())
    run(client, images=[JPG], kind="video")
    assert client.last["input"][0]["content"][1]["detail"] == "auto"


def test_날짜가_붙은_모델_이름도_같은_설정을_쓴다():
    assert openai_client.profile_for("gpt-4o-mini-2024-07-18") == openai_client.PROFILES["gpt-4o-mini"]
    assert openai_client.profile_for("gpt-6-luna") == openai_client.PROFILES["gpt-6-luna"]
    # 이름이 비슷하지만 다른 모델은 같은 설정으로 보지 않는다
    assert openai_client.profile_for("gpt-4o-mini2") == openai_client.UNKNOWN_PROFILE


def test_알_수_없는_모델은_추론_설정을_보내지_않고_출력_제한을_넉넉히_잡는다():
    client = FakeClient(ok())
    run(client, model="some-new-model")
    assert "reasoning" not in client.last
    assert client.last["max_output_tokens"] == 2000


def test_모델을_지정하지_않으면_설정의_모델을_쓴다(monkeypatch):
    monkeypatch.setattr(config.settings, "openai_model", "gpt-4o-mini")
    client = FakeClient(ok())
    summarize([PNG], title="t", memo=None, kind="image", client=client)
    assert client.last["model"] == "gpt-4o-mini"


def test_설정에_모델이_비어_있으면_기본_모델을_쓴다():
    assert config.settings.ai_model == config.DEFAULT_OPENAI_MODEL == "gpt-6-luna"


def test_이미지가_없으면_거절한다():
    client = FakeClient(ok())
    with pytest.raises(AnalysisError) as raised:
        run(client, images=[], kind="video")
    assert raised.value.code == "frames"
    with pytest.raises(AnalysisError) as raised:
        run(client, images=[], kind="image")
    assert raised.value.code == "file_missing"
    assert client.responses.calls == []  # OpenAI를 부르지 않음


# ---------- 결과 정리 ----------


def test_요약문의_앞뒤_공백과_NUL_문자를_지운다():
    result = run(FakeClient(ok(text="  \n 요약\x00 내용 \n ")))
    assert result.text == "요약 내용"


def test_요약문은_2000자까지만_저장한다():
    result = run(FakeClient(ok(text="가" * 5000)))
    assert len(result.text) == config.SUMMARY_MAX_CHARS == 2000


@pytest.mark.parametrize("text", ["", "   \n ", None, "\x00\x00"])
def test_비어_있는_응답은_empty다(text):
    with pytest.raises(AnalysisError) as raised:
        run(FakeClient(ok(text=text)))
    assert raised.value.code == "empty"


def test_사용량이_없는_응답도_처리한다():
    response = ok()
    response.usage = None
    result = run(FakeClient(response))
    assert (result.input_tokens, result.output_tokens) == (None, None)
    assert result.text


def test_모델이_거부하면_refused다():
    refusal = SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="처리할 수 없습니다")])
    with pytest.raises(AnalysisError) as raised:
        run(FakeClient(ok(text="", output=[refusal])))
    assert raised.value.code == "refused"


def test_응답이_실패로_끝나면_server다():
    with pytest.raises(AnalysisError) as raised:
        run(FakeClient(ok(status="failed")))
    assert raised.value.code == "server"


# ---------- 오류 분류 (SDD 6.5) ----------


@pytest.mark.parametrize(
    "error, code",
    [
        (status_error(openai.AuthenticationError, 401), "auth"),
        (status_error(openai.PermissionDeniedError, 403), "auth"),
        (status_error(openai.RateLimitError, 429), "rate_limit"),
        (status_error(openai.RateLimitError, 429, body={"code": "rate_limit_exceeded"}), "rate_limit"),
        (status_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"}), "billing"),
        (status_error(openai.NotFoundError, 404), "model"),
        (status_error(openai.BadRequestError, 400, body={"param": "reasoning.effort", "code": "unsupported_value"}), "model"),
        (status_error(openai.BadRequestError, 400, body={"param": "model", "code": "invalid_value"}), "model"),
        (status_error(openai.BadRequestError, 400, body={"code": "model_not_found"}), "model"),
        (status_error(openai.BadRequestError, 400, body={"code": "invalid_image_format"}), "refused"),
        (status_error(openai.BadRequestError, 400), "refused"),
        (status_error(openai.InternalServerError, 500), "server"),
        (status_error(openai.InternalServerError, 503), "server"),
        (status_error(openai.ConflictError, 409), "unknown"),
        (openai.APITimeoutError(request=_request()), "timeout"),
        (openai.APIConnectionError(request=_request()), "timeout"),
        (openai.OpenAIError("알 수 없는 오류"), "unknown"),
    ],
)
def test_OpenAI_오류를_코드로_바꾼다(error, code):
    with pytest.raises(AnalysisError) as raised:
        run(FakeClient(error))
    assert raised.value.code == code
    assert code in ERROR_MESSAGES  # 모든 코드에 사용자 문구가 있다


def test_오류_원문과_키는_기록에도_예외에도_남지_않는다(caplog):
    caplog.set_level(logging.DEBUG)
    error = status_error(openai.AuthenticationError, 401)
    with pytest.raises(AnalysisError) as raised:
        run(FakeClient(error))
    assert SECRET not in caplog.text
    assert "Incorrect API key" not in caplog.text
    assert SECRET not in str(raised.value) and SECRET not in repr(raised.value)
    assert raised.value.__cause__ is None  # 원문을 담은 원래 예외를 연결해 두지 않음
    assert "code=auth" in caplog.text  # 분류 코드는 남는다


def test_성공_기록에는_요약_내용과_제목이_없다(caplog):
    caplog.set_level(logging.DEBUG)
    run(FakeClient(ok(text="비밀 요약 내용")), title="개인적인 제목", memo="개인적인 메모")
    assert "비밀 요약 내용" not in caplog.text
    assert "개인적인" not in caplog.text
    assert "input_tokens=454" in caplog.text


# ---------- 사용자 문구 ----------


def test_모든_코드에_사용자_문구가_있고_한도는_숫자로_채워진다():
    for code in ERROR_MESSAGES:
        assert openai_client.message_for(code, 30)
    assert "30회" in openai_client.message_for("quota", 30)
    assert "5회" in openai_client.message_for("quota", 5)
    assert "{" not in openai_client.message_for("quota", 30)


def test_코드가_없으면_문구도_없고_모르는_코드는_일반_안내다():
    assert openai_client.message_for(None) is None
    assert openai_client.message_for("") is None
    assert openai_client.message_for("something_else") == ERROR_MESSAGES["unknown"]


# ---------- 클라이언트 만들기 ----------


def test_키가_있으면_제한_시간과_재시도를_정해_클라이언트를_만든다(monkeypatch, real_create_client):
    created = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))
    real_create_client()
    assert created == {"api_key": SECRET, "timeout": 60, "max_retries": 2}


def test_키가_없으면_클라이언트를_만들지_않는다(real_create_client):
    with pytest.raises(AnalysisError) as raised:
        real_create_client()
    assert raised.value.code == "auth"


def test_테스트에서는_실제_클라이언트를_만들_수_없다():
    # conftest의 차단 장치가 동작하는지 확인합니다.
    with pytest.raises(AssertionError):
        openai_client.create_client()
