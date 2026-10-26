"""환경 변수를 읽어 서버 설정으로 제공합니다.

값은 `backend/.env` 파일이나 실제 환경 변수에서 읽고, 없으면 아래 기본값을 사용합니다.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

# 서버를 어느 폴더에서 실행하더라도 같은 파일을 가리키도록 절대 경로로 만듭니다.
DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_DIR / 'database' / 'buildlog.sqlite3').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = DEFAULT_DATABASE_URL


settings = Settings()
