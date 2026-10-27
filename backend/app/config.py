"""환경 변수를 읽어 서버 설정으로 제공합니다.

값은 `backend/.env` 파일이나 실제 환경 변수에서 읽습니다.
`DATABASE_URL`은 기본값이 없습니다. 비어 있으면 다른 데이터베이스로 몰래 연결하지 않고 멈춥니다.
"""

import logging
import re
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 학습 자료함 파일 설정 (비밀값이 아니라 환경 변수로 두지 않습니다). MB는 1,048,576바이트입니다.
# 파일을 쓰는 코드는 이 값을 `config.MATERIALS_UPLOAD_DIR`처럼 모듈을 통해 읽어야 테스트가 폴더를 바꿀 수 있습니다.
MATERIALS_UPLOAD_DIR = BACKEND_DIR / "uploads" / "materials"
MATERIAL_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # PNG, JPG
MATERIAL_MAX_VIDEO_BYTES = 30 * 1024 * 1024  # MP4


class DatabaseConfigError(RuntimeError):
    """DATABASE_URL이 없거나 형식이 틀렸을 때의 오류. 비밀번호가 새지 않도록 주소 내용은 담지 않습니다."""


_CHECKLIST = (
    "확인할 것:\n"
    "  1. backend 폴더에 .env 파일이 있는지 (backend/.env.example을 복사해서 만듭니다)\n"
    "  2. .env 안에 DATABASE_URL=... 줄이 있고, 앞에 #이 없고, 값이 비어 있지 않은지\n"
    "  3. Supabase의 Session pooler 주소(postgresql://postgres.프로젝트ID:비밀번호@...pooler.supabase.com:5432/postgres)인지\n"
    "  4. 비밀번호의 [ ] 괄호를 지웠고, 특수문자(@ : / ? # 등)는 %40 처럼 변환했는지"
)


def _normalize_database_url(raw: str) -> str:
    """주소를 검사하고 psycopg(PostgreSQL 드라이버)용 형식으로 맞춥니다."""
    url = raw.strip().strip("\"'")
    if not url:
        raise DatabaseConfigError("DATABASE_URL이 설정되지 않았습니다.\n" + _CHECKLIST)
    if url.startswith("sqlite"):
        return url  # 자동 테스트처럼 직접 지정한 경우에만 허용합니다.
    match = re.match(r"^(postgres|postgresql)(\+psycopg)?://", url)
    if not match:
        raise DatabaseConfigError(
            "DATABASE_URL이 postgresql:// 로 시작하지 않습니다.\n" + _CHECKLIST
        )
    return "postgresql+psycopg://" + url[match.end():]


# AI 요약 설정 (docs/sdd-ai-summary.md 5장). 비밀값이 아닌 값은 환경 변수로 두지 않고 상수로 둡니다.
DEFAULT_OPENAI_MODEL = "gpt-6-luna"
DEFAULT_AI_DAILY_LIMIT = 30  # 사용자 1명당 하루(한국 날짜) 분석 횟수
AI_OUTPUT_TOKENS = 600  # 요약 한 번에 받는 최대 출력
AI_MAX_FRAMES = 8  # 영상에서 뽑는 장면 수
AI_REQUEST_TIMEOUT_SECONDS = 60
AI_WORKERS = 2  # 동시에 분석하는 최대 개수
SUMMARY_MAX_CHARS = 2000  # 저장하는 요약문의 최대 길이

_ai_logger = logging.getLogger(__name__)


def _clean_secret(value: str) -> str:
    """앞뒤 공백과 따옴표를 지웁니다. (.env에 따옴표를 붙여 넣는 경우가 많습니다)"""
    return value.strip().strip("\"'").strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = ""
    # OpenAI 키. 비어 있으면 AI 요약만 꺼지고 서버와 업로드는 정상 동작합니다.
    # SecretStr이라 설정 객체를 출력해도 값이 가려집니다.
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""  # 비어 있으면 DEFAULT_OPENAI_MODEL
    ai_daily_limit: int = DEFAULT_AI_DAILY_LIMIT

    @field_validator("ai_daily_limit", mode="before")
    @classmethod
    def _valid_daily_limit(cls, value):
        # 잘못된 값(문자, 0 이하)이면 서버를 멈추지 않고 기본값을 쓰며 경고만 남깁니다.
        try:
            number = int(str(value).strip())
        except ValueError:
            number = 0
        if number < 1:
            _ai_logger.warning("AI_DAILY_LIMIT 값이 올바르지 않아 기본값 %s을 사용합니다.", DEFAULT_AI_DAILY_LIMIT)
            return DEFAULT_AI_DAILY_LIMIT
        return number

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key.get_secret_value())

    @property
    def ai_model(self) -> str:
        return self.openai_model.strip() or DEFAULT_OPENAI_MODEL

    def ai_status_line(self) -> str:
        """시작할 때 남기는 한 줄입니다. 키 값은 절대 담지 않습니다."""
        if self.ai_enabled:
            return f"AI 요약: 사용 가능 (모델 {self.ai_model}, 하루 {self.ai_daily_limit}회)"
        return "AI 요약: 꺼짐 (backend/.env에 OPENAI_API_KEY를 넣으면 켜집니다)"


settings = Settings()
settings.database_url = _normalize_database_url(settings.database_url)
settings.openai_api_key = SecretStr(_clean_secret(settings.openai_api_key.get_secret_value()))
if settings.ai_enabled and not settings.openai_api_key.get_secret_value().startswith("sk-"):
    # 프록시·호환 서버를 쓰는 경우도 있어 막지는 않고 알리기만 합니다. (키 값은 기록하지 않음)
    _ai_logger.warning("OPENAI_API_KEY가 'sk-'로 시작하지 않습니다. 키를 올바르게 붙여 넣었는지 확인하세요.")
