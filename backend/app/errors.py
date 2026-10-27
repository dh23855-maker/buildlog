"""화면에 그대로 보여줄 수 있는 한국어 오류 메시지를 만드는 도구입니다."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """상태 코드와 사용자에게 보여줄 메시지를 담은 오류입니다. `field`는 문제가 된 입력 칸입니다."""

    def __init__(self, status_code: int, message: str, field: str | None = None) -> None:
        self.status_code = status_code
        self.message = message
        self.field = field


def _body(message: str, field: str | None) -> dict[str, str | None]:
    return {"detail": message, "field": field}


async def api_error_handler(_request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(_body(error.message, error.field), status_code=error.status_code)


async def validation_error_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
    first = error.errors()[0]
    # 직접 만든 검사(ValueError)의 한국어 메시지는 그대로 보여주고, 나머지는 일반 안내를 보여줍니다.
    if first["type"] == "value_error":
        message = str(first["ctx"]["error"])
    else:
        message = "입력한 내용을 확인해 주세요."
    # body/query/path는 값이 어디서 왔는지 알려주는 표시이므로 빼고, 입력 칸 이름만 남깁니다.
    location = [part for part in first["loc"] if part not in ("body", "query", "path")]
    field = str(location[0]) if location else None
    return JSONResponse(_body(message, field), status_code=422)
