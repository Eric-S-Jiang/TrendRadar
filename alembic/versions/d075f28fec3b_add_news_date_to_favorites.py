"""add_news_date_to_favorites

Revision ID: d075f28fec3b
Revises: 46bb7516c36d
Create Date: 2026-06-11 21:15:44.319761

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd075f28fec3b'
down_revision: Union[str, Sequence[str], None] = '46bb7516c36d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add news_date + denormalized fields to user_favorite_news.

    SQLite batch mode recreates the table, so constraint changes are safe.
    """
    with op.batch_alter_table("user_favorite_news", recreate="always") as batch_op:
        # Drop old unique constraint (user_id, news_item_id) — no date context
        batch_op.drop_constraint("uq_fav_user_news", type_="unique")
        # Add date + cached fields (all nullable for backward compat with existing rows)
        batch_op.add_column(sa.Column("news_date", sa.String(10), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("title", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("url", sa.String(1000), nullable=True))
        batch_op.add_column(sa.Column("platform_id", sa.String(50), nullable=True))
        # New unique constraint includes news_date
        batch_op.create_unique_constraint(
            "uq_fav_user_news_v2", ["user_id", "news_item_id", "news_date"]
        )


def downgrade() -> None:
    with op.batch_alter_table("user_favorite_news", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_fav_user_news_v2", type_="unique")
        batch_op.drop_column("platform_id")
        batch_op.drop_column("url")
        batch_op.drop_column("title")
        batch_op.drop_column("news_date")
        batch_op.create_unique_constraint("uq_fav_user_news", ["user_id", "news_item_id"])
