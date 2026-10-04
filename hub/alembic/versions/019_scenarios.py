"""Add versioned scenarios, resumable items, and execution attempts.

Revision ID: 019
Revises: 018
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(128)),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "slug", name="uq_scenarios_user_slug"),
        sa.CheckConstraint("status IN ('draft','active','disabled')", name="valid_scenario_status"),
    )
    op.create_index(
        "idx_scenarios_user_project_status", "scenarios", ["user_id", "project_id", "status"]
    )
    op.create_table(
        "scenario_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("validation_evidence", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("scenario_id", "version", name="uq_scenario_version"),
    )
    op.create_index(
        "idx_scenario_versions_user_scenario", "scenario_versions", ["user_id", "scenario_id"]
    )
    op.create_table(
        "scenario_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.id"),
            nullable=True,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_versions.id"),
            nullable=True,
        ),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("working_plan", sa.Text()),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("phase", sa.String(128), nullable=False, server_default="ready"),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("environment", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("version_history", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_observation", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_summary", sa.Text()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_signal_key", sa.String(256)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("mode IN ('one_off','continuous')", name="valid_scenario_item_mode"),
        sa.CheckConstraint(
            "status IN ('active','paused','completed')", name="valid_scenario_item_status"
        ),
        sa.CheckConstraint(
            "current_observation IN ('unknown','normal','alert')", name="valid_scenario_observation"
        ),
        sa.CheckConstraint(
            "(scenario_id IS NULL AND version_id IS NULL AND working_plan IS NOT NULL) "
            "OR (scenario_id IS NOT NULL AND version_id IS NOT NULL)",
            name="valid_scenario_item_binding",
        ),
    )
    op.create_index(
        "idx_scenario_items_user_status_due",
        "scenario_items",
        ["user_id", "status", "next_check_at"],
    )
    op.create_index(
        "idx_scenario_items_user_scenario", "scenario_items", ["user_id", "scenario_id"]
    )
    op.create_table(
        "scenario_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_items.id"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_versions.id"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("outcome", sa.String(16)),
        sa.Column("observation", sa.String(16)),
        sa.Column("summary", sa.Text()),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("event_key", sa.String(128)),
        sa.Column("signal", sa.String(32)),
        sa.Column(
            "notification_recommended", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("item_id", "idempotency_key", name="uq_scenario_run_idempotency"),
        sa.CheckConstraint(
            "status IN ('running','completed','abandoned')", name="valid_scenario_run_status"
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('success','failure','skipped')",
            name="valid_scenario_run_outcome",
        ),
        sa.CheckConstraint(
            "observation IS NULL OR observation IN ('unknown','normal','alert')",
            name="valid_scenario_run_observation",
        ),
    )
    op.create_index(
        "idx_scenario_runs_user_item_started", "scenario_runs", ["user_id", "item_id", "started_at"]
    )


def downgrade() -> None:
    # Preserve scenario versions and execution history in existing deployments.
    pass
