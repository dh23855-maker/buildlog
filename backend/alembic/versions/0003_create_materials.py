"""학습 자료함 표 만들기

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("memo", sa.String(length=1000), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('image', 'video')", name="ck_materials_kind"),
        sa.CheckConstraint(
            "content_type IN ('image/png', 'image/jpeg', 'video/mp4')", name="ck_materials_content_type"
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_materials_size_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_name"),
    )
    op.create_index("ix_materials_user_created", "materials", ["user_id", "created_at", "id"])


def downgrade() -> None:
    # 표만 지웁니다. backend/uploads 의 파일은 지우지 않으므로 필요하면 직접 정리합니다.
    op.drop_index("ix_materials_user_created", table_name="materials")
    op.drop_table("materials")
