"""Record the completed NetBox Sync database/schema naming transition."""

# Alembic revision attributes follow framework conventions.
# pylint: disable=invalid-name

from alembic import op
import sqlalchemy as sa

revision = '0003_netbox_sync_naming'
down_revision = '0002_sync_run_history'
branch_labels = None
depends_on = None


def upgrade(schema):
    """Accept canonical production state or an isolated, guarded test schema."""
    if schema == 'netbox_sync':
        return
    database = op.get_bind().execute(sa.text('SELECT current_database()')).scalar_one()
    if database != 'netbox_sync_test' or not schema.startswith('netbox_sync_test_'):
        raise RuntimeError('NetBox Sync naming migration requires canonical state')


def downgrade(schema):
    """Never rename production state backward automatically."""
    raise RuntimeError('Downgrade is unsupported; use the reviewed naming rollback plan')
