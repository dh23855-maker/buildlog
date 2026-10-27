"""BuildLog FastAPI 서버의 시작점입니다."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool

from app import analysis
from app.config import settings
from app.errors import ApiError, api_error_handler, validation_error_handler
from app.routers import account, auth, materials

# 시작할 때 AI 요약이 켜져 있는지 한 줄 남깁니다. (키 값은 담지 않습니다)
logging.getLogger("uvicorn.error").info(settings.ai_status_line())

_log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """서버가 켜질 때 한 번: 이전 실행에서 중단된 AI 요약(pending)을 실패로 정리합니다."""
    try:
        count = await run_in_threadpool(analysis.recover_interrupted)
        if count:
            _log.warning("서버가 다시 시작되어 중단된 AI 요약 %s건을 실패로 표시했습니다.", count)
    except Exception:  # noqa: BLE001 - 정리에 실패해도 서버 시작은 막지 않습니다.
        _log.exception("중단된 AI 요약을 정리하지 못했습니다")
    yield


# 실제 서비스(production)에서는 API 설명 화면을 열지 않습니다.
_docs_enabled = settings.app_env != "production"

app = FastAPI(
    title="BuildLog API",
    lifespan=lifespan,
    docs_url="/api/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _docs_enabled else None,
)

app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(auth.router)
app.include_router(account.router)
app.include_router(materials.router)

@app.get("/api/health")
def health() -> dict[str, str]:
    """서버가 켜져 있는지 확인합니다."""
    return {"status": "ok"}
