"""Frozen registry v1 baseline: create clean schema or validate existing data in place."""

# Revision names/attributes and the dynamic op proxy are Alembic conventions.
# pylint: disable=invalid-name,no-member

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0001_registry_baseline'
down_revision = None
branch_labels = None
depends_on = None


def tables(schema):
    """Historical snapshot, deliberately independent of runtime initialize()."""
    metadata = sa.MetaData(schema=schema)
    meta = sa.Table(
        'schema_meta', metadata,
        sa.Column('key', sa.Text, primary_key=True),
        sa.Column('value', sa.Text, nullable=False),
    )
    text_fields = (
        'name', 'source_type', 'address', 'site_slug', 'device_role_slug',
        'platform_slug', 'device_type_slug', 'cluster_type_slug', 'cluster_name',
        'username', 'token_id_provider', 'token_id_key', 'token_secret_provider',
        'token_secret_key',
    )
    sources = sa.Table(
        'sources', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('source_instance', sa.Text, nullable=False, unique=True),
        *(sa.Column(name, sa.Text, nullable=False) for name in text_fields),
        *(sa.Column(name, sa.Boolean, nullable=False)
          for name in ('enabled', 'sync_enabled', 'verify_ssl')),
        sa.Column('sync_interval_seconds', sa.Integer, nullable=False),
        sa.Column('legacy_identity_owner', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('settings', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *(sa.Column(name, sa.DateTime(timezone=True), nullable=False,
                    server_default=sa.text('CURRENT_TIMESTAMP'))
          for name in ('created_at', 'updated_at')),
        sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name='settings_is_object'),
        sa.CheckConstraint('sync_interval_seconds > 0', name='positive_sync_interval'),
    )
    return meta, sources


def _normalized(value):
    return ''.join(str(value or '').lower().split()).replace('(', '').replace(')', '').replace('::text', '')


def validate(connection, expected):
    """Reject structural drift; never stamp unknown/partial legacy tables."""
    inspector = sa.inspect(connection)
    for table in expected:
        actual = {column['name']: column for column in inspector.get_columns(table.name, schema=table.schema)}
        if set(actual) != set(table.columns.keys()):
            raise RuntimeError('Legacy registry columns differ from baseline')
        for column in table.columns:
            found = actual[column.name]
            expected_type = column.type.compile(dialect=connection.dialect)
            found_type = found['type'].compile(dialect=connection.dialect)
            default = str(column.server_default.arg) if column.server_default is not None else None
            if (expected_type != found_type or column.nullable != found['nullable']
                    or _normalized(default) != _normalized(found.get('default'))):
                raise RuntimeError('Legacy registry column definition differs from baseline')
        primary = inspector.get_pk_constraint(table.name, schema=table.schema)
        if primary['constrained_columns'] != [column.name for column in table.primary_key]:
            raise RuntimeError('Legacy registry primary key differs from baseline')
    sources = expected[1]
    unique = inspector.get_unique_constraints('sources', schema=sources.schema)
    if not any(item['column_names'] == ['source_instance'] for item in unique):
        raise RuntimeError('Legacy source_instance uniqueness is missing')
    checks = inspector.get_check_constraints('sources', schema=sources.schema)
    expressions = {_normalized(item['sqltext']) for item in checks}
    for expression in ("jsonb_typeof(settings) = 'object'", 'sync_interval_seconds > 0'):
        if _normalized(expression) not in expressions:
            raise RuntimeError('Legacy registry safety constraint is missing')


def upgrade(schema):
    """Preserve legacy rows and timestamps; only Alembic adds its version row."""
    connection = op.get_bind()
    expected = tables(schema)
    existing = set(sa.inspect(connection).get_table_names(schema=schema))
    present = existing.intersection({'sources', 'schema_meta'})
    if present and present != {'sources', 'schema_meta'}:
        raise RuntimeError('Partial legacy registry schema is not supported')
    if not present:
        for table in expected:
            table.create(connection)
        connection.execute(expected[0].insert().values(key='schema_version', value='1'))
    else:
        validate(connection, expected)
        version = connection.execute(
            sa.select(expected[0].c.value).where(expected[0].c.key == 'schema_version')
        ).scalar_one_or_none()
        if version != '1':
            raise RuntimeError('Unsupported legacy registry schema version')


def downgrade(schema):
    """No destructive rollback of a production registry."""
    raise RuntimeError('Downgrade is unsupported; use a reviewed forward fix')
