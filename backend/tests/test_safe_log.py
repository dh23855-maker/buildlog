import logging

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.safe_log import log_exception
from tests.test_materials_upload import png, upload

# 값은 변수로 둡니다. (기록에는 소스 코드 줄이 남으므로, raise 줄에 값을 직접 적으면 그 줄이 찍힙니다. 실제 코드의 소스 줄에는 비밀값이 없습니다.)
SECRET = "sk-SECRET-KEY-123456789"
TITLE = "개인적인 제목"
MEMO = "개인적인 메모"
OUTER = "바깥 오류 비밀"
INNER = "안쪽 오류 비밀"
SQL_PARAMS = {"title": TITLE, "memo": MEMO}


def raise_secret():
    raise RuntimeError(f"인증 실패: Bearer {SECRET} {TITLE} {INNER}")


def test_종류와_코드_위치만_기록하고_메시지는_남기지_않는다(caplog):
    logger = logging.getLogger("test.safe")
    caplog.set_level(logging.DEBUG)
    try:
        raise_secret()
    except RuntimeError as error:
        log_exception(logger, "처리 실패: id=7", error)

    assert "처리 실패: id=7" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "raise_secret" in caplog.text  # 어느 함수에서 났는지는 남는다
    # 소스 코드 줄은 기록되지만 실행 중에 채워진 값(키·제목·메시지)은 기록되지 않는다
    assert SECRET not in caplog.text and TITLE not in caplog.text and INNER not in caplog.text


def test_연결된_원인_예외의_메시지도_남기지_않는다(caplog):
    caplog.set_level(logging.DEBUG)
    try:
        try:
            raise_secret()
        except RuntimeError as inner:
            raise ValueError(OUTER) from inner
    except ValueError as error:
        log_exception(logging.getLogger("test.safe"), "실패", error)
    assert SECRET not in caplog.text and INNER not in caplog.text and OUTER not in caplog.text


@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_데이터베이스_오류_기록에_제목과_메모_값이_남지_않는다(logged_in, monkeypatch, caplog, operation):
    caplog.set_level(logging.DEBUG)
    created = upload(logged_in, title=TITLE, memo=MEMO).json()

    def boom(self):
        # SQLAlchemy 오류 메시지에는 SQL 값이 함께 들어갑니다.
        raise OperationalError("INSERT INTO materials", SQL_PARAMS, Exception("연결 끊김"))

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", boom)
        if operation == "upload":
            response = upload(logged_in, title=TITLE + "2", memo=MEMO + "2")
        else:
            response = logged_in.delete(f"/api/materials/{created['id']}")

    assert response.status_code == 500
    assert "개인적인" not in caplog.text
    assert "OperationalError" in caplog.text  # 종류는 남아 원인 파악은 가능
