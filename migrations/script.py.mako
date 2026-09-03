"""${message}"""

from alembic import op
import sqlalchemy as sa

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade(schema):
    raise NotImplementedError('Review an additive, schema-qualified migration before use')


def downgrade(schema):
    raise RuntimeError('Destructive downgrade is not supported; use a reviewed forward fix')
