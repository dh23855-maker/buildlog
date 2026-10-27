"""AI 요약 열과 하루 사용 횟수 표 만들기

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 자료는 모두 'skipped'(분석 안 함)가 됩니다. (server_default)
    with op.batch_alter_table("materials") as batch:
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("analysis_status", sa.String(length=10), nullable=False, server_default="skipped")
        )
        batch.add_column(sa.Column("analysis_error", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("analysis_model", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_materials_analysis_status", "analysis_status IN ('skipped', 'pending', 'done', 'failed')"
        )

    op.create_table(
        "ai_usage",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 0", name="ck_ai_usage_count_nonneg"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "day"),
    )


def downgrade() -> None:
    # 주의: 추가한 열과 ai_usage 표를 지우므로 저장된 AI 요약과 사용 횟수가 사라집니다.
    op.drop_table("ai_usage")
    with op.batch_alter_table("materials") as batch:
        batch.drop_constraint("ck_materials_analysis_status", type_="check")
        batch.drop_column("analysis_model")
        batch.drop_column("analyzed_at")
        batch.drop_column("analysis_error")
        batch.drop_column("analysis_status")
        batch.drop_column("summary")
