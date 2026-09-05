"""Add durable per-source synchronization run history."""

# Alembic revision attributes and operation proxy follow framework conventions.
# pylint: disable=invalid-name,no-member

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0002_sync_run_history'
down_revision = '0001_registry_baseline'
branch_labels = None
depends_on = None


def upgrade(schema):
    """Add history objects without changing registry v1 tables or rows."""
    table = op.create_table(
        'sync_runs',
        sa.Column('run_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source_instance', sa.Text(), nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('trigger', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('plan_digest', sa.Text(), nullable=True),
        sa.Column('planner_version', sa.Text(), nullable=True),
        sa.Column('create_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('update_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('no_change_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('review_required_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('blocked_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ignored_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unsupported_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('retain_only_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('error_message_safe', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Text(), nullable=False),
        sa.CheckConstraint("source_type IN ('proxmox', 'esxi')", name='sync_runs_source_type'),
        sa.CheckConstraint(
            "source_instance ~ '^[a-z0-9][a-z0-9._-]{1,62}$'",
            name='sync_runs_source_instance',
        ),
        sa.CheckConstraint("trigger IN ('manual', 'scheduled')", name='sync_runs_trigger'),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED_BEFORE_WRITE', "
            "'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN', 'BLOCKED', 'LOCKED', 'FAILED')",
            name='sync_runs_status',
        ),
        sa.CheckConstraint('duration_ms IS NULL OR duration_ms >= 0', name='sync_runs_duration'),
        sa.CheckConstraint(
            "plan_digest IS NULL OR plan_digest ~ '^[a-f0-9]{64}$'",
            name='sync_runs_plan_digest',
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('APPLY_LOCKED', 'PLAN_BLOCKED', "
            "'PLAN_STALE', 'CONFIRMATION_EXPIRED', 'CONFIRMATION_INVALID', "
            "'CONFIRMATION_SOURCE_MISMATCH', 'FAILED_BEFORE_WRITE', "
            "'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN', 'APPLY_FAILED')",
            name='sync_runs_error_code',
        ),
        sa.CheckConstraint(
            'char_length(created_by) BETWEEN 1 AND 128 AND '
            '(planner_version IS NULL OR char_length(planner_version) <= 128) AND '
            '(error_message_safe IS NULL OR char_length(error_message_safe) <= 256)',
            name='sync_runs_bounded_text',
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND finished_at IS NULL AND duration_ms IS NULL) OR "
            "(status <> 'RUNNING' AND finished_at IS NOT NULL AND duration_ms IS NOT NULL)",
            name='sync_runs_lifecycle',
        ),
        sa.CheckConstraint(
            'create_count >= 0 AND update_count >= 0 AND no_change_count >= 0 AND '
            'review_required_count >= 0 AND blocked_count >= 0 AND ignored_count >= 0 AND '
            'unsupported_count >= 0 AND retain_only_count >= 0',
            name='sync_runs_nonnegative_counts',
        ),
        schema=schema,
    )
    op.create_index('ix_sync_runs_started_at', table.name, [sa.text('started_at DESC')],
                    schema=schema)
    op.create_index('ix_sync_runs_source_started', table.name,
                    ['source_instance', sa.text('started_at DESC')], schema=schema)
    op.create_index('ix_sync_runs_status', table.name, ['status'], schema=schema)
    op.create_index('ix_sync_runs_trigger', table.name, ['trigger'], schema=schema)


def downgrade(schema):
    """Never remove production history automatically."""
    raise RuntimeError('Downgrade is unsupported; preserve synchronization history')
