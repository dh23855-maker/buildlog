"""학습 자료함 파일을 서버 폴더에 안전하게 저장하고 지웁니다.

- 저장 파일 이름은 서버가 만든 임의의 이름입니다. 사용자가 올린 파일 이름은 경로에 쓰지 않습니다.
- 파일 내용의 앞부분 표식으로 종류를 확인하고, 크기는 파일을 읽으며 직접 셉니다.
- 업로드 폴더는 `app.config.MATERIALS_UPLOAD_DIR`를 호출할 때마다 읽어서(테스트가 바꿀 수 있게) 사용합니다.
"""

import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import app.config as config
from app.errors import ApiError
from app.safe_log import log_exception

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
UNSUPPORTED_MESSAGE = "PNG, JPG, MP4 파일만 올릴 수 있어요."
SAVE_FAILED_MESSAGE = "파일을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."

# 확장자 → (파일 종류, 형식 이름, 저장 확장자)
_BY_EXTENSION = {
    "png": ("image", "image/png", ".png"),
    "jpg": ("image", "image/jpeg", ".jpg"),
    "jpeg": ("image", "image/jpeg", ".jpg"),
    "mp4": ("video", "video/mp4", ".mp4"),
}
_LABELS = {"image/png": "PNG", "image/jpeg": "JPG", "video/mp4": "MP4"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class StoredFile:
    """임시 이름으로 저장이 끝난 파일입니다. `commit_file()`을 해야 최종 이름이 됩니다."""

    tmp_path: Path
    final_path: Path
    storage_name: str
    kind: str
    content_type: str
    size_bytes: int
    original_filename: str


def _detect(head: bytes) -> str | None:
    """파일 앞부분으로 형식 이름을 알아냅니다. 알 수 없으면 None."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # MP4는 5~8번째 바이트가 'ftyp'입니다. QuickTime(MOV)은 같은 표식이지만 MP4가 아니므로 제외합니다.
    if head[4:8] == b"ftyp" and head[8:12] != b"qt  ":
        return "video/mp4"
    return None


def _limit_for(content_type: str) -> int:
    if content_type == "video/mp4":
        return config.MATERIAL_MAX_VIDEO_BYTES
    return config.MATERIAL_MAX_IMAGE_BYTES


def _base_name(name: str | None) -> str:
    return re.split(r"[\\/]", name or "")[-1]


def clean_original_filename(name: str | None, fallback_ext: str) -> str:
    """화면에 보여줄 원래 파일 이름만 남깁니다. 폴더 구분자와 제어 문자를 지우고 255자로 자릅니다."""
    base = _CONTROL_CHARS.sub("", _base_name(name)).strip()
    if not base or base in {".", ".."}:
        base = f"file{fallback_ext}"
    return base[:255]


def _extension(name: str | None) -> str:
    base = _base_name(name)
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        # 지우지 못한 파일은 어디에도 연결되지 않습니다. 사람이 정리할 수 있도록 기록만 남깁니다.
        log_exception(logger, f"파일을 지우지 못했습니다: {path.name}", error)


def save_upload(source: BinaryIO, filename: str | None, declared_type: str | None) -> StoredFile:
    """올라온 파일을 검사하며 업로드 폴더의 임시 이름으로 저장합니다. 문제가 있으면 아무것도 남기지 않습니다."""
    rule = _BY_EXTENSION.get(_extension(filename))
    if rule is None:
        raise ApiError(415, UNSUPPORTED_MESSAGE, "file")
    kind, expected_type, ext = rule
    # 브라우저가 알려준 형식이 있으면 확장자와 같아야 합니다. 비어 있는 경우만 확장자를 믿습니다.
    if declared_type and declared_type != expected_type:
        raise ApiError(415, UNSUPPORTED_MESSAGE, "file")

    upload_dir = Path(config.MATERIALS_UPLOAD_DIR)
    storage_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = upload_dir / f".tmp-{uuid.uuid4().hex}"
    final_path = upload_dir / storage_name
    # 저장 위치가 반드시 업로드 폴더 안인지 확인합니다.
    if final_path.parent != upload_dir or tmp_path.parent != upload_dir:
        raise ApiError(500, SAVE_FAILED_MESSAGE)

    size = 0
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "wb") as out:
            first = source.read(CHUNK_SIZE)
            if not first:
                raise ApiError(422, "비어 있는 파일은 올릴 수 없어요.", "file")
            if _detect(first) != expected_type:
                raise ApiError(415, UNSUPPORTED_MESSAGE, "file")
            limit = _limit_for(expected_type)
            chunk = first
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise ApiError(
                        413,
                        f"{_LABELS[expected_type]} 파일은 {limit // (1024 * 1024)}MB까지 올릴 수 있어요.",
                        "file",
                    )
                out.write(chunk)
                chunk = source.read(CHUNK_SIZE)
    except ApiError:
        _remove(tmp_path)
        raise
    except OSError as error:
        log_exception(logger, "업로드 파일을 쓰지 못했습니다", error)
        _remove(tmp_path)
        raise ApiError(500, SAVE_FAILED_MESSAGE) from None

    return StoredFile(
        tmp_path=tmp_path,
        final_path=final_path,
        storage_name=storage_name,
        kind=kind,
        content_type=expected_type,
        size_bytes=size,
        original_filename=clean_original_filename(filename, ext),
    )


def commit_file(stored: StoredFile) -> None:
    """임시 파일을 최종 이름으로 바꿉니다."""
    try:
        os.replace(stored.tmp_path, stored.final_path)
    except OSError as error:
        log_exception(logger, "업로드 파일 이름을 바꾸지 못했습니다", error)
        _remove(stored.tmp_path)
        raise ApiError(500, SAVE_FAILED_MESSAGE) from None


def discard_file(stored: StoredFile) -> None:
    """저장 도중 실패했을 때 임시 파일과 최종 파일을 모두 지웁니다."""
    _remove(stored.tmp_path)
    _remove(stored.final_path)


_STORED_NAME = re.compile(r"[0-9a-f]{32}\.(png|jpg|mp4)")


def stored_path(storage_name: str) -> Path | None:
    """저장 이름에 해당하는 파일 경로입니다. 서버가 만든 형식이 아니면(폴더 구분자 등) None을 돌려줍니다."""
    if not _STORED_NAME.fullmatch(storage_name or ""):
        logger.error("올바르지 않은 저장 이름입니다: %r", storage_name)
        return None
    return Path(config.MATERIALS_UPLOAD_DIR) / storage_name


def delete_stored(storage_name: str) -> None:
    """저장된 파일을 지웁니다. 이미 없으면 넘어가고, 지우지 못하면 기록만 남깁니다."""
    path = stored_path(storage_name)
    if path is not None:
        _remove(path)
