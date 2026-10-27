"""예외를 기록할 때 비밀과 개인 내용이 새지 않게 합니다.

`logger.exception()`은 예외 메시지를 그대로 기록합니다. 그런데 외부 서비스·데이터베이스 오류의 메시지에는
API 키 일부나 SQL 값(사용자가 입력한 제목·메모)이 들어 있을 수 있습니다.
그래서 **예외 종류와 코드 위치(어느 파일 몇 번째 줄)만** 기록하고 메시지와 값은 남기지 않습니다.
"""

import logging
import traceback


def log_exception(logger: logging.Logger, message: str, error: BaseException) -> None:
    frames = "".join(traceback.format_tb(error.__traceback__))
    logger.error("%s: %s\n%s", message, type(error).__name__, frames.rstrip())
