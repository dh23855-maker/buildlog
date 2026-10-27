from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AiUsage(Base):
    """사용자별 하루 AI 요약 횟수입니다. (docs/sdd-ai-summary.md 3.2)

    자료를 지워도 횟수가 돌아오지 않도록 `materials`와 별도로 셉니다.
    `day`는 한국 날짜(Asia/Seoul)입니다. 사용자가 지워지면 함께 지워집니다.
    """

    __tablename__ = "ai_usage"
    __table_args__ = (CheckConstraint("count >= 0", name="ck_ai_usage_count_nonneg"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
