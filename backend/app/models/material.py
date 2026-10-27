from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import utc_now


class Material(Base):
    """학습 자료함의 자료 정보입니다. 파일 자체는 서버의 업로드 폴더에 따로 저장됩니다."""

    __tablename__ = "materials"
    __table_args__ = (
        # 내 자료를 최신순으로 불러오는 요청을 위한 인덱스입니다. (user_id 단독 조회도 이 인덱스를 씁니다)
        Index("ix_materials_user_created", "user_id", "created_at", "id"),
        # 서버가 먼저 검사하지만, 잘못된 값이 데이터베이스에 남지 않도록 한 번 더 막습니다.
        CheckConstraint("kind IN ('image', 'video')", name="ck_materials_kind"),
        CheckConstraint(
            "content_type IN ('image/png', 'image/jpeg', 'video/mp4')", name="ck_materials_content_type"
        ),
        CheckConstraint("size_bytes > 0", name="ck_materials_size_positive"),
        CheckConstraint(
            "analysis_status IN ('skipped', 'pending', 'done', 'failed')", name="ck_materials_analysis_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 자료를 올린 사람. 사용자가 지워지면 자료 정보도 함께 지워집니다.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # image 또는 video
    # 사용자가 올린 원래 파일 이름입니다. 화면 표시용이며 파일 경로로는 절대 쓰지 않습니다.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # 서버가 만든 임의의 저장 파일 이름입니다.
    storage_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # ---- AI 요약 (docs/sdd-ai-summary.md 3장) ----
    # 요약문. 서버가 2,000자로 자른 평문입니다. 분석이 끝난(done) 자료에만 값이 있습니다.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # skipped(분석 안 함) · pending(진행 중) · done(완료) · failed(실패)
    analysis_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="skipped", server_default="skipped"
    )
    # 실패 코드(auth, rate_limit, timeout 등). 화면에는 코드를 문장으로 바꿔 보여줍니다.
    analysis_error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 분석이 끝난(성공·실패) 시각, UTC
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 요약을 만든 모델 이름 (품질·비용 추적용)
    analysis_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @property
    def analysis_message(self) -> str | None:
        """분석이 실패했을 때 사용자에게 보여줄 문장입니다. (저장된 코드를 문장으로 바꿈)"""
        if self.analysis_status != "failed":
            return None
        from app.openai_client import message_for  # 순환 참조를 피하려고 필요할 때 불러옵니다.

        return message_for(self.analysis_error or "unknown")
