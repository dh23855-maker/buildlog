import logging
import struct
import zlib

import pytest
from pydantic import SecretStr

import app.config as config
from app import openai_client
from app.config import Settings
from app.tools import check_ai

SECRET = "sk-SECRET-KEY-123456789"


def make_settings(**overrides) -> Settings:
    # .env 파일을 읽지 않고, 테스트용 DB 주소와 주어진 값만으로 설정을 만듭니다.
    return Settings(_env_file=None, database_url="sqlite://", **overrides)


# ---------- 설정 ----------


def test_테스트에서는_개발자의_실제_키와_상관없이_AI가_꺼져_있다():
    assert config.settings.ai_enabled is False
    assert config.settings.openai_api_key.get_secret_value() == ""


def test_키가_비어_있으면_AI가_꺼진다():
    assert make_settings(openai_api_key="").ai_enabled is False


def test_키가_있으면_AI가_켜진다():
    assert make_settings(openai_api_key=SECRET).ai_enabled is True


def test_설정을_출력해도_키가_가려진다():
    settings = make_settings(openai_api_key=SECRET)
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert SECRET not in repr(settings.openai_api_key)
    assert settings.openai_api_key.get_secret_value() == SECRET


def test_시작_기록_한_줄에는_키가_없다():
    on = make_settings(openai_api_key=SECRET, openai_model="gpt-4o-mini", ai_daily_limit=12).ai_status_line()
    off = make_settings().ai_status_line()
    assert SECRET not in on and SECRET not in off
    assert "사용 가능" in on and "gpt-4o-mini" in on and "12회" in on
    assert "꺼짐" in off and "OPENAI_API_KEY" in off


@pytest.mark.parametrize(
    "raw, expected",
    [
        (f'"{SECRET}"', SECRET),
        (f"'{SECRET}'", SECRET),
        (f"  {SECRET}  ", SECRET),
        (f' "{SECRET}" ', SECRET),
        ("", ""),
        ("   ", ""),
    ],
)
def test_키_앞뒤의_공백과_따옴표를_지운다(raw, expected):
    assert config._clean_secret(raw) == expected


def test_모델이_비어_있으면_기본_모델이고_지정하면_그_모델이다():
    assert make_settings().ai_model == "gpt-6-luna"
    assert make_settings(openai_model="  ").ai_model == "gpt-6-luna"
    assert make_settings(openai_model="gpt-4o-mini").ai_model == "gpt-4o-mini"


def test_하루_한도_기본값은_30이다():
    assert make_settings().ai_daily_limit == 30


@pytest.mark.parametrize("value, expected", [("12", 12), (7, 7), (" 5 ", 5), ("1", 1)])
def test_하루_한도를_바꿀_수_있다(value, expected):
    assert make_settings(ai_daily_limit=value).ai_daily_limit == expected


@pytest.mark.parametrize("value", ["abc", "0", "-5", "", "3.5"])
def test_하루_한도가_잘못되면_서버를_멈추지_않고_기본값과_경고를_쓴다(value, caplog):
    caplog.set_level(logging.WARNING)
    assert make_settings(ai_daily_limit=value).ai_daily_limit == 30
    assert "AI_DAILY_LIMIT" in caplog.text


def test_환경_변수가_설정으로_들어온다(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("AI_DAILY_LIMIT", "9")
    settings = Settings(_env_file=None, database_url="sqlite://")
    assert (settings.ai_enabled, settings.ai_model, settings.ai_daily_limit) == (True, "gpt-4o-mini", 9)


def test_env_example에는_항목_이름만_있고_키_값이_없다():
    from pathlib import Path

    text = (Path(config.BACKEND_DIR) / ".env.example").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" in text and "OPENAI_MODEL" in text and "AI_DAILY_LIMIT" in text
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        assert not line.strip().startswith("OPENAI_API_KEY=sk-")
    assert "sk-" not in text.replace("sk- 로 시작", "")  # 설명 문구 말고는 키처럼 보이는 값이 없다


# ---------- 연결 확인 명령 ----------


class FakeResponses:
    def __init__(self, outcome):
        self.outcome = outcome

    def create(self, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome):
        self.responses = FakeResponses(outcome)


def _ok():
    from types import SimpleNamespace

    return SimpleNamespace(
        output_text="BUILDLOG라는 글자가 있는 이미지입니다.\n- 파란 밑줄",
        usage=SimpleNamespace(input_tokens=454, output_tokens=62),
        status="completed",
        output=[],
    )


def test_샘플_이미지는_올바른_PNG다():
    png = check_ai.make_sample_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (636, 174)
    assert len(png) < 10_000  # 작은 파일이라 요청이 가볍다
    # 이미지 데이터 조각을 풀어 크기가 맞는지 확인
    start = png.index(b"IDAT")
    length = struct.unpack(">I", png[start - 4:start])[0]
    raw = zlib.decompress(png[start + 4:start + 4 + length])
    assert len(raw) == height * (1 + width * 3)


def test_키가_없으면_실패하고_확인할_것을_알려준다(capsys):
    assert check_ai.main([]) == 1
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out and ".env" in out and "실패" in out


def test_성공하면_요약과_사용량을_보여주고_키는_출력하지_않는다(monkeypatch, capsys):
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))
    assert check_ai.main([], client=FakeClient(_ok())) == 0
    out = capsys.readouterr().out
    assert "성공" in out and "gpt-6-luna" in out
    assert "입력 454 / 출력 62" in out
    assert "BUILDLOG라는 글자" in out
    assert SECRET not in out


@pytest.mark.parametrize(
    "code, hint_word",
    [("auth", "키가 올바른지"), ("billing", "Billing"), ("model", "OPENAI_MODEL"), ("timeout", "인터넷"), ("rate_limit", "잠시 후")],
)
def test_실패하면_코드와_확인할_것을_알려준다(monkeypatch, capsys, code, hint_word):
    monkeypatch.setattr(config.settings, "openai_api_key", SecretStr(SECRET))

    class Failing:
        class responses:
            @staticmethod
            def create(**kwargs):
                raise openai_client.AnalysisError(code)

    # summarize는 OpenAI 예외를 AnalysisError로 바꿔 던지므로, 여기서는 이미 바뀐 오류를 직접 던져 출력만 확인한다.
    assert check_ai.main([], client=Failing()) == 1
    out = capsys.readouterr().out
    assert f"({code})" in out and hint_word in out
    assert SECRET not in out
