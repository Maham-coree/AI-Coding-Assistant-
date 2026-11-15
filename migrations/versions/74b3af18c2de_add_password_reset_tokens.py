"""add password reset tokens

Revision ID: 74b3af18c2de
Revises: 585d43297987
Create Date: 2026-11-15 00:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "74b3af18c2de"
down_revision = "585d43297987"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "password_reset_token" in inspector.get_table_names():
        existing_columns = {column["name"] for column in inspector.get_columns("password_reset_token")}
        required_columns = {"id", "user_id", "token_hash", "expires_at", "used_at", "created_at"}
        if not required_columns.issubset(existing_columns):
            raise RuntimeError("Existing password_reset_token table has an incompatible schema.")
        unique_constraints = inspector.get_unique_constraints("password_reset_token")
        if not any(constraint.get("column_names") == ["token_hash"] for constraint in unique_constraints):
            raise RuntimeError("Existing password_reset_token table lacks the token hash uniqueness constraint.")
        foreign_keys = inspector.get_foreign_keys("password_reset_token")
        if not any(
            foreign_key.get("constrained_columns") == ["user_id"]
            and foreign_key.get("referred_table") == "user"
            for foreign_key in foreign_keys
        ):
            raise RuntimeError("Existing password_reset_token table lacks its user foreign key.")
        existing_index_columns = {
            tuple(index.get("column_names") or [])
            for index in inspector.get_indexes("password_reset_token")
        }
        for column_name in ("user_id", "expires_at"):
            if (column_name,) not in existing_index_columns:
                op.create_index(
                    f"ix_password_reset_token_{column_name}",
                    "password_reset_token",
                    [column_name],
                    unique=False,
                )
        return

    op.create_table(
        "password_reset_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
    )
    op.create_index(
        "ix_password_reset_token_user_id",
        "password_reset_token",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_token_expires_at",
        "password_reset_token",
        ["expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_password_reset_token_expires_at", table_name="password_reset_token")
    op.drop_index("ix_password_reset_token_user_id", table_name="password_reset_token")
    op.drop_table("password_reset_token")
