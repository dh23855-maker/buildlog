import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.config as config
from app import analysis, storage
from app.database import get_db
from app.errors import ApiError
from app.models.material import Material
from app.models.user import User
from app.schemas.material import (
    MaterialCounts,
    MaterialListResponse,
    MaterialResponse,
    clean_memo,
    clean_title,
)
from app.safe_log import log_exception
from app.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/materials", tags=["materials"])

# 제목·메모·경계 문자열이 차지하는 여유분입니다. 이보다 큰 요청은 어떤 파일이든 한도를 넘습니다.
_REQUEST_OVERHEAD = 1024 * 1024
_TOO_LARGE = "파일이 너무 커요. PNG·JPG는 5MB, MP4는 30MB까지 올릴 수 있어요."
_BAD_REQUEST = "올바르지 않은 요청입니다. 화면을 새로고침한 뒤 다시 시도해 주세요."
_DB_FAILED = "자료를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
_DELETE_FAILED = "자료를 삭제하지 못했습니다. 잠시 후 다시 시도해 주세요."
# 없는 자료와 다른 사람의 자료에 똑같이 쓰는 메시지입니다. (자료가 있다는 사실도 알려주지 않기 위해서)
_NOT_FOUND = "자료를 찾을 수 없습니다."


def _text_field(form, name: str) -> str:
    value = form.get(name)
    return value if isinstance(value, str) else ""


def _want_ai(form) -> bool:
    """등록 폼의 "AI 요약하기" 값입니다. 보내지 않았으면(예전 화면 등) 켜짐으로 봅니다."""
    return _text_field(form, "ai_summary").strip().lower() not in {"false", "0", "off", "no", "n"}


def _create(
    db: Session, user: User, title: str, memo: str | None, upload: UploadFile, want_ai: bool = True
) -> Material:
    """파일 저장과 자료 정보 저장을 한 묶음으로 처리합니다. 실패하면 파일과 데이터베이스 모두 되돌립니다.

    AI 요약은 저장이 **확정된 뒤에** 예약합니다. 요약이 실패해도 저장은 그대로 남습니다.
    """
    stored = storage.save_upload(upload.file, upload.filename, upload.content_type)
    material = Material(
        user_id=user.id,
        title=title,
        memo=memo,
        kind=stored.kind,
        original_filename=stored.original_filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        storage_name=stored.storage_name,
        # 키가 없거나 사용자가 껐으면 skipped, 아니면 pending (자료 저장과 같은 트랜잭션에서 정합니다)
        analysis_status=analysis.decide_initial_status(want_ai),
    )
    try:
        db.add(material)
        db.flush()  # 데이터베이스가 받아들이는지 먼저 확인합니다. (아직 확정하지 않음)
        storage.commit_file(stored)  # 파일을 최종 이름으로 바꾼 뒤
        db.commit()  # 마지막에 자료 정보를 확정합니다.
    except SQLAlchemyError as error:
        # 데이터베이스 오류 메시지에는 SQL 값(제목·메모)이 들어 있을 수 있어 종류와 위치만 기록합니다.
        log_exception(logger, "자료 정보를 저장하지 못했습니다", error)
        db.rollback()
        storage.discard_file(stored)
        raise ApiError(500, _DB_FAILED) from None
    except BaseException:
        db.rollback()
        storage.discard_file(stored)
        raise

    if material.analysis_status == "pending" and not analysis.submit_or_fail(material.id):
        db.refresh(material)  # 예약에 실패해 failed로 바뀐 상태를 응답에 반영
    return material


@router.post("", response_model=MaterialResponse, status_code=201)
async def create_material(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    # 파일은 로그인을 확인한 뒤에 받습니다. (FastAPI의 자동 파일 받기는 로그인 확인보다 먼저 파일을 받습니다)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > config.MATERIAL_MAX_VIDEO_BYTES + _REQUEST_OVERHEAD:
        raise ApiError(413, _TOO_LARGE, "file")

    try:
        form = await request.form(max_files=2, max_fields=10)
    except StarletteHTTPException:
        raise ApiError(422, _BAD_REQUEST) from None

    try:
        try:
            title = clean_title(_text_field(form, "title"))
        except ValueError as error:
            raise ApiError(422, str(error), "title") from None
        try:
            memo = clean_memo(_text_field(form, "memo"))
        except ValueError as error:
            raise ApiError(422, str(error), "memo") from None

        files = [item for item in form.getlist("file") if isinstance(item, UploadFile)]
        if not files:
            raise ApiError(422, "파일을 선택해 주세요.", "file")
        if len(files) > 1:
            raise ApiError(422, "자료마다 파일은 1개만 올릴 수 있어요.", "file")

        return await run_in_threadpool(_create, db, user, title, memo, files[0], _want_ai(form))
    finally:
        await form.close()


def _own_material(db: Session, user: User, material_id: int) -> Material:
    """로그인한 사용자 본인의 자료만 찾습니다. 없거나 다른 사람의 자료이면 똑같이 '없음'으로 답합니다."""
    material = db.scalar(select(Material).where(Material.id == material_id, Material.user_id == user.id))
    if material is None:
        raise ApiError(404, _NOT_FOUND)
    return material


@router.get("", response_model=MaterialListResponse)
def list_materials(
    kind: Literal["image", "video"] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialListResponse:
    query = select(Material).where(Material.user_id == user.id)
    if kind is not None:
        query = query.where(Material.kind == kind)
    # 최신 등록순입니다. 등록 시각이 같으면 나중에 등록한 것이 먼저 옵니다.
    items = db.scalars(query.order_by(Material.created_at.desc(), Material.id.desc())).all()

    # 개수는 필터와 관계없이 내 전체 자료 기준입니다.
    per_kind = dict(
        db.execute(
            select(Material.kind, func.count()).where(Material.user_id == user.id).group_by(Material.kind)
        ).all()
    )
    image, video = per_kind.get("image", 0), per_kind.get("video", 0)
    return MaterialListResponse(
        items=[MaterialResponse.model_validate(item) for item in items],
        counts=MaterialCounts(all=image + video, image=image, video=video),
        ai_enabled=config.settings.ai_enabled,
    )


@router.get("/{material_id}/file")
def get_material_file(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    material = _own_material(db, user, material_id)
    path = storage.stored_path(material.storage_name)
    if path is None or not path.is_file():
        # 자료 정보는 있는데 파일이 사라진 경우입니다. 서버 안의 사정은 화면에 알리지 않습니다.
        logger.error("자료 %s의 파일이 없습니다", material.id)
        raise ApiError(404, _NOT_FOUND)
    # 저장된 형식으로만 알리고(nosniff), 공유 캐시에 남지 않게 합니다. Range 요청(영상 탐색)은 FileResponse가 처리합니다.
    return FileResponse(
        path,
        media_type=material.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/{material_id}", status_code=204)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    material = _own_material(db, user, material_id)
    storage_name = material.storage_name
    try:
        db.delete(material)
        db.commit()
    except SQLAlchemyError as error:
        log_exception(logger, "자료 정보를 지우지 못했습니다", error)
        db.rollback()
        raise ApiError(500, _DELETE_FAILED) from None
    # 자료 정보를 먼저 확정해 지운 뒤 파일을 지웁니다. 파일을 못 지워도 남는 파일은 어디서도 접근할 수 없습니다.
    storage.delete_stored(storage_name)
    return Response(status_code=204)


@router.post("/{material_id}/analyze", response_model=MaterialResponse, status_code=202)
def analyze_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    """실패했거나 아직 요약하지 않은 자료의 AI 요약을 (다시) 시작합니다. 바로 돌아오며 결과는 나중에 목록에 나타납니다."""
    # 남의 자료와 없는 자료는 AI 설정과 상관없이 같은 404로 먼저 걸러냅니다.
    _own_material(db, user, material_id)
    if not config.settings.ai_enabled:
        raise ApiError(503, "AI 요약을 사용할 수 없어요.")
    material = analysis.request_reanalysis(db, user.id, material_id)  # 분석 중·완료는 409
    if not analysis.submit_or_fail(material.id):
        db.refresh(material)
    return material
