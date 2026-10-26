"""BuildLog FastAPI 서버의 시작점입니다."""

from fastapi import FastAPI

from app.config import settings

# 실제 서비스(production)에서는 API 설명 화면을 열지 않습니다.
_docs_enabled = settings.app_env != "production"

app = FastAPI(
    title="BuildLog API",
    docs_url="/api/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _docs_enabled else None,
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """서버가 켜져 있는지 확인합니다."""
    return {"status": "ok"}
