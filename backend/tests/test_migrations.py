from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings
from app.db.migrations import upgrade_business_database


BACKEND_ROOT = Path(__file__).parents[1]


@contextmanager
def migration_database(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("EVAS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        yield config, create_engine(database_url)
    finally:
        get_settings.cache_clear()


def test_upgrade_from_initial_workflow_preserves_run_node_and_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with migration_database(tmp_path, monkeypatch) as (config, engine):
        command.upgrade(config, "0001_initial_workflow_tables")
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO video_projects "
                    "(id, title, target_platform, language, aspect_ratio, duration_seconds, status, "
                    "estimated_cost_total, actual_cost_total, created_at, updated_at) "
                    "VALUES (1, 'Legacy project', 'douyin', 'zh-CN', '9:16', 15, 'draft', "
                    "0, 0, :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, project_id, checkpoint_thread_id, status, pending_confirmation, "
                    "workflow_status, started_at, updated_at, metadata) "
                    "VALUES (11, 1, 'legacy-workflow', 'completed', 0, 'script_review', "
                    ":now, :now, '{}')"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_node_runs "
                    "(id, workflow_run_id, project_id, node_name, status, started_at, retry_count, metadata) "
                    "VALUES (12, 11, 1, 'creative_script', 'succeeded', :now, 0, '{}')"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(id, project_id, workflow_run_id, workflow_node_run_id, agent_type, status, "
                    "input_payload, created_at) "
                    "VALUES (13, 1, 11, 12, 'creative_script', 'succeeded', '{}', :now)"
                ),
                {"now": now},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(text("SELECT id FROM workflow_runs")).scalars().all() == [11]
            assert connection.execute(text("SELECT id FROM workflow_node_runs")).scalars().all() == [12]
            assert connection.execute(text("SELECT id FROM agent_runs")).scalars().all() == [13]
            table_names = set(inspect(connection).get_table_names())
            assert not any(name.startswith("legacy_0001_") for name in table_names)


def test_upgrade_from_creative_runs_backfills_visible_workflow_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with migration_database(tmp_path, monkeypatch) as (config, engine):
        command.upgrade(config, "0004_verified_assets")
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO video_projects "
                    "(id, title, target_platform, language, aspect_ratio, duration_seconds, status, "
                    "estimated_cost_total, actual_cost_total, created_at, updated_at) "
                    "VALUES (1, 'Legacy creative project', 'douyin', 'zh-CN', '9:16', 15, "
                    "'ready_for_review', 0, 0, :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO creative_runs "
                    "(id, project_id, thread_id, status, action, confidence, provider_key, model_key, "
                    "revision_count, input_payload, output_payload, started_at, completed_at) "
                    "VALUES (21, 1, 'legacy-creative', 'ready_for_review', 'review_plan', 0.91, "
                    "'local', NULL, 1, :input_payload, :output_payload, :now, :now)"
                ),
                {
                    "input_payload": '{"campaign_goal": "保留历史目标"}',
                    "output_payload": '{"schema_version": 1, "decision": {"legacy": true}}',
                    "now": now,
                },
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT checkpoint_thread_id, status, workflow_status, pending_confirmation, metadata "
                    "FROM workflow_runs"
                )
            ).mappings().one()
            assert row["checkpoint_thread_id"] == "legacy-creative"
            assert row["status"] == "waiting_confirmation"
            assert row["workflow_status"] == "generation_waiting_confirmation"
            assert row["pending_confirmation"] == 1
            metadata = json.loads(row["metadata"])
            assert metadata["legacy_creative_run_id"] == 21
            assert metadata["campaign_goal"] == "保留历史目标"


def test_creative_run_backfill_does_not_duplicate_existing_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with migration_database(tmp_path, monkeypatch) as (config, engine):
        command.upgrade(config, "0005_restore_workflow")
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO video_projects "
                    "(id, title, target_platform, language, aspect_ratio, duration_seconds, status, "
                    "estimated_cost_total, actual_cost_total, created_at, updated_at) "
                    "VALUES (1, 'Deduplicated project', 'douyin', 'zh-CN', '9:16', 15, "
                    "'ready_for_review', 0, 0, :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO creative_runs "
                    "(id, project_id, thread_id, status, provider_key, revision_count, "
                    "input_payload, started_at) "
                    "VALUES (31, 1, 'shared-thread', 'ready_for_review', 'local', 0, '{}', :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, project_id, checkpoint_thread_id, status, pending_confirmation, "
                    "workflow_status, started_at, updated_at, metadata) "
                    "VALUES (32, 1, 'shared-thread', 'waiting_confirmation', 1, "
                    "'generation_waiting_confirmation', :now, :now, '{}')"
                ),
                {"now": now},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one() == 1


def test_unversioned_creative_run_base_schema_resumes_from_actual_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with migration_database(tmp_path, monkeypatch) as (config, engine):
        command.upgrade(config, "0002_creative_runs")
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO video_projects "
                    "(id, title, target_platform, language, aspect_ratio, duration_seconds, status, "
                    "estimated_cost_total, actual_cost_total, created_at, updated_at) "
                    "VALUES (1, 'Unversioned project', 'douyin', 'zh-CN', '9:16', 15, "
                    "'draft', 0, 0, :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO project_assets "
                    "(id, project_id, asset_type, storage_key, mime_type, metadata, created_at) "
                    "VALUES (2, 1, 'product_image', 'missing.jpg', 'image/jpeg', '{}', :now)"
                ),
                {"now": now},
            )
            connection.execute(text("DROP TABLE alembic_version"))

        upgrade_business_database()

        with engine.connect() as connection:
            creative_columns = {column["name"] for column in inspect(connection).get_columns("creative_runs")}
            assert "thread_id" in creative_columns
            thread_indexes = inspect(connection).get_indexes("creative_runs")
            assert any(
                index["unique"] and index["column_names"] == ["thread_id"]
                for index in thread_indexes
            )
            assert connection.execute(
                text("SELECT asset_type FROM project_assets WHERE id = 2")
            ).scalar_one() == "legacy_unverified_image"
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                "0007_prompt_revision"
            )


def test_unversioned_thread_schema_only_isolates_unverified_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with migration_database(tmp_path, monkeypatch) as (config, engine):
        command.upgrade(config, "0003_langgraph_thread")
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO video_projects "
                    "(id, title, target_platform, language, aspect_ratio, duration_seconds, status, "
                    "estimated_cost_total, actual_cost_total, created_at, updated_at) "
                    "VALUES (1, 'Mixed assets', 'douyin', 'zh-CN', '9:16', 15, "
                    "'draft', 0, 0, :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO project_assets "
                    "(id, project_id, asset_type, storage_key, mime_type, metadata, created_at) VALUES "
                    "(2, 1, 'product_image', 'missing.jpg', 'image/jpeg', '{}', :now), "
                    "(3, 1, 'product_image', 'verified.jpg', 'image/jpeg', "
                    "'{\"verified\": true}', :now)"
                ),
                {"now": now},
            )
            connection.execute(text("DROP TABLE alembic_version"))

        upgrade_business_database()

        with engine.connect() as connection:
            assets = connection.execute(
                text("SELECT id, asset_type FROM project_assets ORDER BY id")
            ).all()
            assert assets == [(2, "legacy_unverified_image"), (3, "product_image")]
