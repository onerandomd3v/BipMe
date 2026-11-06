"""Enable pgvector extension.

Revision ID: 0001_enable_vector
Revises:
"""

from alembic import op

revision = "0001_enable_vector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the extension required for Post Profile embeddings."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Do not drop a potentially shared extension automatically."""
    pass
