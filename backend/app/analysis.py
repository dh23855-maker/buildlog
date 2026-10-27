"""AI 요약 분석을 실행하고 상태를 관리합니다. (docs/sdd-ai-summary.md 4장, 8장)

- 분석 상태: skipped(안 함) · pending(진행 중) · done(완료) · failed(실패)
- 상태 변경은 모두 `WHERE analysis_status = …` 조건이 붙은 UPDATE 한 문장으로 합니다.
  (읽고 나서 쓰면 동시에 두 번 분석되거나, 삭제·중단된 자료에 결과를 쓸 수 있습니다.)
- OpenAI를 기다리는 동안에는 데이터베이스 연결을 잡고 있지 않습니다.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.config as config
from app import openai_client, storage, video_frames
from app.database import SessionLocal
from app.errors import ApiError
from app.models.ai_usage import AiUsage
from app.models.material import Material
from app.openai_client import AnalysisError, ImageInput
from app.safe_log import log_exception

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------- 하루 한도


def kst_day(now: datetime) -> date:
    """시각이 속한 한국 날짜입니다. 하루 한도는 한국 날짜 기준입니다."""
    return now.astimezone(KST).date()


def today_kst() -> date:
    return kst_day(datetime.now(UTC))


def reserve_quota(db: Session, user_id: int) -> bool:
    """오늘 한도 안이면 횟수를 1 올리고 True, 한도에 닿았으면 False를 돌려줍니다.

    `UPDATE … SET count = count + 1 WHERE … AND count < 한도` 한 문장이라 여러 요청이 동시에 와도 한도를 넘지 않습니다.
    오늘 처음이면 행을 새로 넣고, 동시에 다른 요청이 먼저 넣었으면(중복) 한 번 더 올려 봅니다.
    """
    limit = config.settings.ai_daily_limit
    day = today_kst()

    def bump() -> bool:
        result = db.execute(
            update(AiUsage)
            .where(AiUsage.user_id == user_id, AiUsage.day == day, AiUsage.count < limit)
            .values(count=AiUsage.count + 1)
        )
        return result.rowcount == 1

    if bump():
        db.commit()
        return True
    if db.scalar(select(AiUsage.count).where(AiUsage.user_id == user_id, AiUsage.day == day)) is not None:
        db.rollback()
        return False  # 오늘 행이 있는데 한도에 닿음
    try:
        db.execute(insert(AiUsage).values(user_id=user_id, day=day, count=1))  # 한도는 1 이상이므로 항상 통과
        db.commit()
        return True
    except IntegrityError:
        db.rollback()  # 같은 순간에 다른 요청이 오늘 행을 먼저 만들었습니다.
    if bump():
        db.commit()
        return True
    db.rollback()
    return False


# ---------------------------------------------------------------- 상태 정하기·바꾸기


def decide_initial_status(want_ai: bool) -> str:
    """새로 저장하는 자료의 분석 상태입니다. 키가 없거나 사용자가 끄면 분석하지 않습니다."""
    return "pending" if want_ai and config.settings.ai_enabled else "skipped"


def _finish_done(material_id: int, result: openai_client.SummaryResult) -> bool:
    """진행 중(pending)인 자료에만 결과를 저장합니다. 그 사이 삭제·중단되었으면 False."""
    with SessionLocal() as db:
        saved = db.execute(
            update(Material)
            .where(Material.id == material_id, Material.analysis_status == "pending")
            .values(
                summary=result.text,
                analysis_status="done",
                analysis_error=None,
                analyzed_at=datetime.now(UTC),
                analysis_model=result.model,
            )
        ).rowcount
        db.commit()
    return saved == 1


def _finish_failed(material_id: int, code: str) -> bool:
    with SessionLocal() as db:
        saved = db.execute(
            update(Material)
            .where(Material.id == material_id, Material.analysis_status == "pending")
            .values(analysis_status="failed", analysis_error=code, analyzed_at=datetime.now(UTC))
        ).rowcount
        db.commit()
    return saved == 1


def request_reanalysis(db: Session, user_id: int, material_id: int) -> Material:
    """실패했거나 아직 분석하지 않은 자료를 다시 분석 대기(pending)로 바꿉니다.

    본인 자료인지와 상태를 한 문장에서 함께 확인합니다. 분석 중·완료 자료는 409입니다.
    """
    changed = db.execute(
        update(Material)
        .where(
            Material.id == material_id,
            Material.user_id == user_id,
            Material.analysis_status.in_(("failed", "skipped")),
        )
        .values(analysis_status="pending", analysis_error=None, analyzed_at=None)
    ).rowcount
    db.commit()
    material = db.scalar(select(Material).where(Material.id == material_id, Material.user_id == user_id))
    if material is None:
        raise ApiError(404, "자료를 찾을 수 없습니다.")
    if changed != 1:
        db.refresh(material)
        raise ApiError(409, "이미 분석 중이에요." if material.analysis_status == "pending" else "이미 요약이 있어요.")
    db.refresh(material)
    return material


def recover_interrupted() -> int:
    """서버가 켜질 때 한 번 실행합니다. 이 서버 안에서 돌던 분석은 프로세스와 함께 사라지므로,
    시작 시점에 남아 있는 pending은 모두 중단된 것입니다. 실패(interrupted)로 바꿔 다시 분석할 수 있게 합니다."""
    with SessionLocal() as db:
        count = db.execute(
            update(Material)
            .where(Material.analysis_status == "pending")
            .values(analysis_status="failed", analysis_error="interrupted", analyzed_at=datetime.now(UTC))
        ).rowcount
        db.commit()
    return count


# ---------------------------------------------------------------- 분석 실행


def _load_images(kind: str, content_type: str, storage_name: str) -> list[ImageInput]:
    path = storage.stored_path(storage_name)
    if path is None or not path.is_file():
        raise AnalysisError("file_missing")
    if kind == "video":
        # 영상은 장면(JPEG) 여러 장으로 바꿔서 보냅니다. ffmpeg는 별도 프로세스로 실행됩니다.
        try:
            return [ImageInput(frame, "image/jpeg") for frame in video_frames.extract_frames(path)]
        except video_frames.FrameExtractionError:
            raise AnalysisError("frames") from None
    try:
        return [ImageInput(path.read_bytes(), content_type)]
    except OSError as error:
        log_exception(logger, "분석할 파일을 읽지 못했습니다", error)
        raise AnalysisError("file_missing") from None


def _run(material_id: int) -> None:
    # 1) 필요한 값만 읽고 세션을 닫습니다. (OpenAI를 기다리는 동안 DB 연결을 잡지 않기 위해)
    with SessionLocal() as db:
        row = db.execute(
            select(
                Material.user_id, Material.kind, Material.content_type, Material.storage_name,
                Material.title, Material.memo, Material.analysis_status,
            ).where(Material.id == material_id)
        ).one_or_none()
    if row is None or row.analysis_status != "pending":
        logger.info("분석을 건너뜁니다: material=%s (없거나 진행 중이 아님)", material_id)
        return

    try:
        # 2) 파일 읽기. 파일이 없으면 한도를 쓰지 않고 실패 처리합니다.
        images = _load_images(row.kind, row.content_type, row.storage_name)
        # 3) 하루 한도 차감 (OpenAI를 부르기 직전)
        with SessionLocal() as db:
            if not reserve_quota(db, row.user_id):
                raise AnalysisError("quota")
        # 4) OpenAI 호출
        result = openai_client.summarize(images, title=row.title, memo=row.memo, kind=row.kind)
    except AnalysisError as error:
        stored = _finish_failed(material_id, error.code)
        logger.info("분석 실패: material=%s code=%s 저장=%s", material_id, error.code, stored)
        return

    # 5) 결과 저장 (그 사이 삭제되었으면 버립니다)
    if _finish_done(material_id, result):
        logger.info("분석 완료: material=%s model=%s", material_id, result.model)
    else:
        logger.info("분석 결과를 버립니다: material=%s (삭제되었거나 상태가 바뀜)", material_id)


def run_analysis(material_id: int) -> None:
    """분석 한 건을 실행합니다. 어떤 오류도 밖으로 던지지 않습니다. (서버와 다른 요청에 영향을 주지 않기 위해)"""
    try:
        _run(material_id)
    except Exception as error:  # noqa: BLE001 - 분석 스레드의 오류가 서버로 번지지 않게 모두 잡습니다.
        log_exception(logger, f"분석 중 예기치 못한 오류: material={material_id}", error)
        try:
            _finish_failed(material_id, "unknown")
        except Exception as save_error:  # noqa: BLE001
            # 이 저장마저 실패하면 다음 서버 시작 때 recover_interrupted가 정리합니다.
            log_exception(logger, f"실패 상태를 저장하지 못했습니다: material={material_id}", save_error)


# ---------------------------------------------------------------- 실행기


_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=config.AI_WORKERS, thread_name_prefix="ai-analysis")
        return _executor


def submit(material_id: int) -> None:
    """분석을 예약합니다. 바로 돌아오며, 실제 분석은 별도 스레드(동시 2개)에서 진행됩니다."""
    _get_executor().submit(run_analysis, material_id)


def submit_or_fail(material_id: int) -> bool:
    """분석을 예약하고, 예약 자체가 실패하면 자료를 실패(unknown)로 표시합니다. 업로드를 실패시키지 않기 위해서입니다."""
    try:
        submit(material_id)
        return True
    except Exception as error:  # noqa: BLE001
        log_exception(logger, f"분석을 예약하지 못했습니다: material={material_id}", error)
        try:
            _finish_failed(material_id, "unknown")
        except Exception as save_error:  # noqa: BLE001
            log_exception(logger, f"실패 상태를 저장하지 못했습니다: material={material_id}", save_error)
        return False
