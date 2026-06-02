"""narrow release platform to win/mac

只维护 Mac arm64 + Windows x64，去掉 releases.platform 的 'linux' 取值。
004 已带 linux 上线，这里收窄 CHECK 约束（表无数据，直接 drop+recreate）。

Revision ID: 005
Revises: 004
Create Date: 2026-06-02 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_release_platform", "releases", schema="studio", type_="check")
    op.create_check_constraint(
        "ck_release_platform", "releases", "platform IN ('win', 'mac')", schema="studio"
    )


def downgrade() -> None:
    op.drop_constraint("ck_release_platform", "releases", schema="studio", type_="check")
    op.create_check_constraint(
        "ck_release_platform", "releases", "platform IN ('win', 'mac', 'linux')", schema="studio"
    )
