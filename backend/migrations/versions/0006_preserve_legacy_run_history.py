"""把过渡版本中的历史运行恢复到当前工作流记录。

Revision ID: 0006_preserve_run_history
Revises: 0005_restore_workflow
Create Date: 2026-07-14
"""

from collections.abc import Sequence
from typing import Any

from alembic import op
import sqlalchemy as sa


revision: str = "0006_preserve_run_history"
down_revision: str | None = "0005_restore_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_WORKFLOW_TABLES = (
    "legacy_0001_workflow_runs",
    "legacy_0001_workflow_node_runs",
    "legacy_0001_agent_runs",
)


def upgrade() -> None:
    """恢复 0001 工作流记录，并把 creative_runs 回填为当前 WorkflowRun。"""

    connection = op.get_bind()
    table_names = set(sa.inspect(connection).get_table_names())

    if LEGACY_WORKFLOW_TABLES[0] in table_names:
        _restore_legacy_workflow_tables(connection)
        table_names = set(sa.inspect(connection).get_table_names())

    if "creative_runs" in table_names:
        _backfill_creative_runs(connection)


def downgrade() -> None:
    raise RuntimeError("历史运行回填不可安全逆转。")


def _restore_legacy_workflow_tables(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    old_runs = sa.Table(LEGACY_WORKFLOW_TABLES[0], metadata, autoload_with=connection)
    old_nodes = sa.Table(LEGACY_WORKFLOW_TABLES[1], metadata, autoload_with=connection)
    old_agents = sa.Table(LEGACY_WORKFLOW_TABLES[2], metadata, autoload_with=connection)
    runs = sa.Table("workflow_runs", metadata, autoload_with=connection)
    nodes = sa.Table("workflow_node_runs", metadata, autoload_with=connection)
    agents = sa.Table("agent_runs", metadata, autoload_with=connection)

    _copy_rows(connection, old_runs, runs)
    _copy_rows(
        connection,
        old_nodes,
        nodes,
        defaults={"review_run_id": None, "generation_task_id": None},
    )
    _copy_rows(connection, old_agents, agents)
    for table in (runs, nodes, agents):
        _sync_postgresql_sequence(connection, table)

    op.drop_table(LEGACY_WORKFLOW_TABLES[2])
    op.drop_table(LEGACY_WORKFLOW_TABLES[1])
    op.drop_table(LEGACY_WORKFLOW_TABLES[0])


def _copy_rows(
    connection: sa.Connection,
    source: sa.Table,
    target: sa.Table,
    *,
    defaults: dict[str, object] | None = None,
) -> None:
    source_columns = {column.name for column in source.columns}
    default_values = defaults or {}
    columns = [column.name for column in target.columns]
    selected_columns = [
        sa.literal(default_values[column]).label(column)
        if column in default_values
        else source.c[column]
        for column in columns
        if column in source_columns or column in default_values
    ]
    insert_columns = [column.name for column in selected_columns]
    connection.execute(
        target.insert().from_select(insert_columns, sa.select(*selected_columns))
    )


def _sync_postgresql_sequence(connection: sa.Connection, table: sa.Table) -> None:
    if connection.dialect.name != "postgresql":
        return
    sequence_name = connection.execute(
        sa.text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
        {"table_name": table.name},
    ).scalar_one_or_none()
    if not sequence_name:
        return
    quoted_table = connection.dialect.identifier_preparer.quote(table.name)
    connection.execute(
        sa.text(
            f"SELECT setval(CAST(:sequence_name AS regclass), "
            f"COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {quoted_table}"
        ),
        {"sequence_name": sequence_name},
    )


def _backfill_creative_runs(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    creative_runs = sa.Table("creative_runs", metadata, autoload_with=connection)
    workflow_runs = sa.Table("workflow_runs", metadata, autoload_with=connection)
    existing_threads = set(
        connection.execute(sa.select(workflow_runs.c.checkpoint_thread_id)).scalars()
    )

    for legacy in connection.execute(sa.select(creative_runs)).mappings():
        thread_id = str(legacy["thread_id"])
        if thread_id in existing_threads:
            continue

        public_status = str(legacy["status"])
        workflow_status, current_node, pending_confirmation = _workflow_projection(public_status)
        input_payload = _json_object(legacy["input_payload"])
        output_payload = _json_object(legacy["output_payload"])
        metadata_payload: dict[str, object] = {
            "legacy_creative_run_id": legacy["id"],
            "public_status": public_status,
            "action": legacy["action"],
            "confidence": legacy["confidence"],
            "provider_key": legacy["provider_key"],
            "model_key": legacy["model_key"],
            "revision_count": legacy["revision_count"],
            "input": input_payload,
        }
        campaign_goal = input_payload.get("campaign_goal")
        if isinstance(campaign_goal, str):
            metadata_payload["campaign_goal"] = campaign_goal
        if output_payload:
            metadata_payload["decision_payload"] = output_payload

        connection.execute(
            workflow_runs.insert().values(
                project_id=legacy["project_id"],
                checkpoint_thread_id=thread_id,
                status=_run_status(public_status),
                current_node=current_node,
                pending_confirmation=pending_confirmation,
                workflow_status=workflow_status,
                started_at=legacy["started_at"],
                updated_at=legacy["completed_at"] or legacy["started_at"],
                completed_at=legacy["completed_at"],
                error_message=legacy["error_message"],
                metadata=metadata_payload,
            )
        )
        existing_threads.add(thread_id)


def _workflow_projection(status: str) -> tuple[str, str | None, bool]:
    if status == "ready_for_review":
        return "generation_waiting_confirmation", "confirm_generation_task", True
    if status in {"quality_blocked", "blocked"}:
        return "review_failed", "review_cost_gate", True
    if status == "failed":
        return "review_failed", None, False
    if status == "running":
        return "understanding_running", "product_understanding", False
    return status, None, False


def _run_status(status: str) -> str:
    if status == "failed":
        return "failed"
    if status == "running":
        return "running"
    if status in {"ready_for_review", "quality_blocked", "blocked"}:
        return "waiting_confirmation"
    return "completed"


def _json_object(value: Any) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
