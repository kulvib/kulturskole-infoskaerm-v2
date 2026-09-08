"""55A durable fresh-install release binding on enrollment tokens.

Revision ID: 20260908_55a_enroll_binding
Revises: 20260829_54a_display_parity
"""
from alembic import op
import sqlalchemy as sa

revision = "20260908_55a_enroll_binding"
down_revision = "20260829_54a_display_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable by design: pre-55A unconsumed codes must fail closed instead of
    # being rebound to whatever release happens to be current after migration.
    op.add_column("enrollmenttoken", sa.Column("fresh_install_release_id", sa.String(length=160), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_version", sa.String(length=32), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_release_sequence", sa.Integer(), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_bundle_sha256", sa.String(length=64), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_bundle_size", sa.Integer(), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_approval_reference", sa.String(length=200), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_candidate_sha256", sa.String(length=64), nullable=True))
    op.add_column("enrollmenttoken", sa.Column("fresh_install_source_commit", sa.String(length=40), nullable=True))


def downgrade() -> None:
    for name in reversed((
        "fresh_install_release_id", "fresh_install_version", "fresh_install_release_sequence",
        "fresh_install_bundle_sha256", "fresh_install_bundle_size", "fresh_install_approval_reference",
        "fresh_install_candidate_sha256", "fresh_install_source_commit",
    )):
        op.drop_column("enrollmenttoken", name)
