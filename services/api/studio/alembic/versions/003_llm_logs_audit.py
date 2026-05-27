"""llm_logs audit columns

把 LLM round-trip 变成可审计的单元：把每条 log 接回 conversation /
distill_job / outbound_message，并把"调用当时模型实际看到的 persona/card"
和（distill）"fold 出来的新 persona/card" 一起快照下来。

Revision ID: 003
Revises: 002
Create Date: 2026-05-27 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("llm_logs", schema="studio") as batch:
        batch.add_column(sa.Column("conversation_id", sa.String(48), nullable=True))
        batch.add_column(sa.Column("distill_job_id", sa.String(48), nullable=True))
        batch.add_column(sa.Column("outbound_message_id", sa.BigInteger, nullable=True))
        batch.add_column(sa.Column("window_index", sa.Integer, nullable=True))
        batch.add_column(sa.Column("windows_total", sa.Integer, nullable=True))
        batch.add_column(sa.Column("latency_ms", sa.Integer, nullable=True))
        batch.add_column(sa.Column("prompt_tokens", sa.Integer, nullable=True))
        batch.add_column(sa.Column("completion_tokens", sa.Integer, nullable=True))
        batch.add_column(sa.Column("is_error", sa.Boolean, nullable=True))
        batch.add_column(sa.Column("persona_md_snapshot", sa.Text, nullable=True))
        batch.add_column(sa.Column("card_md_snapshot", sa.Text, nullable=True))
        batch.add_column(sa.Column("persona_md_after", sa.Text, nullable=True))
        batch.add_column(sa.Column("card_md_after", sa.Text, nullable=True))

    op.create_index(
        "ix_llm_logs_conversation_id", "llm_logs", ["conversation_id"], schema="studio"
    )
    op.create_index(
        "ix_llm_logs_distill_job_id", "llm_logs", ["distill_job_id"], schema="studio"
    )
    op.create_index(
        "ix_llm_logs_created_at", "llm_logs", ["created_at"], schema="studio"
    )


def downgrade() -> None:
    op.drop_index("ix_llm_logs_created_at", table_name="llm_logs", schema="studio")
    op.drop_index("ix_llm_logs_distill_job_id", table_name="llm_logs", schema="studio")
    op.drop_index("ix_llm_logs_conversation_id", table_name="llm_logs", schema="studio")
    with op.batch_alter_table("llm_logs", schema="studio") as batch:
        for col in (
            "conversation_id", "distill_job_id", "outbound_message_id",
            "window_index", "windows_total",
            "latency_ms", "prompt_tokens", "completion_tokens", "is_error",
            "persona_md_snapshot", "card_md_snapshot",
            "persona_md_after", "card_md_after",
        ):
            batch.drop_column(col)
