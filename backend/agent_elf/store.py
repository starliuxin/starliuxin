from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_elf.models import Plan, Requirement, RunStatus, StageId


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path != Path(":memory:"):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_input TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT,
                    token_budget INTEGER NOT NULL CHECK (token_budget > 0),
                    total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
                    plan_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    stage TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    parent_version INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, stage, version)
                );
                CREATE TABLE IF NOT EXISTS requirements (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    module TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    acceptance TEXT NOT NULL,
                    prototype_element TEXT NOT NULL,
                    related_steps_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    dirty INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requirement_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requirement_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    version INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    message TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    stages_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_run(self, user_input: str, token_budget: int) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, user_input, status, token_budget, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, user_input, RunStatus.CREATED.value, token_budget, timestamp, timestamp),
            )
            self._event(connection, run_id, "run.created", None, "Run 已创建", {})
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["status"] = RunStatus(result["status"])
        result["plan"] = (
            Plan.model_validate_json(result.pop("plan_json")) if result["plan_json"] else None
        )
        if result["error"] is None:
            result.pop("error")
        return result

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, user_input, status, current_stage, token_budget, total_tokens, "
                "created_at, updated_at FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        stage: StageId | None = None,
        message: str,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, current_stage = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, stage.value if stage else None, error, _now(), run_id),
            )
            self._event(
                connection,
                run_id,
                f"run.{status.value.lower()}",
                stage.value if stage else None,
                message,
                detail or {},
            )

    def set_stage(self, run_id: str, stage: StageId, message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET current_stage = ?, updated_at = ? WHERE id = ?",
                (stage.value, _now(), run_id),
            )
            self._event(connection, run_id, "stage.started", stage.value, message, {})

    def save_plan(self, run_id: str, plan: Plan) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET plan_json = ?, updated_at = ? WHERE id = ?",
                (plan.model_dump_json(), _now(), run_id),
            )
            self._event(
                connection,
                run_id,
                "plan.ready",
                None,
                "Planner 已生成包含最终目标的计划",
                {"step_count": len(plan.steps)},
            )

    def add_tokens(
        self, run_id: str, input_tokens: int, output_tokens: int, model: str, latency_ms: int
    ) -> int:
        amount = input_tokens + output_tokens
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET total_tokens = total_tokens + ?, updated_at = ? WHERE id = ?",
                (amount, _now(), run_id),
            )
            row = connection.execute(
                "SELECT total_tokens FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            total = int(row["total_tokens"])
            self._event(
                connection,
                run_id,
                "model.usage",
                None,
                "记录模型用量",
                {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "total_tokens": total,
                },
            )
        return total

    def increase_token_budget(self, run_id: str, additional_tokens: int) -> int:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET token_budget = token_budget + ?, updated_at = ? WHERE id = ?",
                (additional_tokens, _now(), run_id),
            )
            row = connection.execute(
                "SELECT token_budget FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            total = int(row["token_budget"])
            self._event(
                connection,
                run_id,
                "budget.increased",
                None,
                "用户明确提高了本 Run 的 token 硬上限。",
                {"additional_tokens": additional_tokens, "token_budget": total},
            )
        return total

    def add_artifact(self, run_id: str, stage: str, kind: str, content: str) -> dict[str, Any]:
        artifact_id = str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM artifacts WHERE run_id = ? AND stage = ?",
                (run_id, stage),
            ).fetchone()
            version = int(row["version"] or 0) + 1
            parent_version = version - 1 if version > 1 else None
            connection.execute(
                """
                INSERT INTO artifacts
                    (id, run_id, stage, version, kind, content, parent_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, run_id, stage, version, kind, content, parent_version, timestamp),
            )
            self._event(
                connection,
                run_id,
                "artifact.created",
                stage,
                f"{stage} 产物 v{version} 已保存",
                {"artifact_id": artifact_id, "kind": kind, "version": version},
            )
        return {
            "id": artifact_id,
            "run_id": run_id,
            "stage": stage,
            "version": version,
            "kind": kind,
            "content": content,
            "parent_version": parent_version,
            "created_at": timestamp,
        }

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at, stage, version",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_artifact(self, run_id: str, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND id = ?", (run_id, artifact_id)
            ).fetchone()
        return dict(row) if row else None

    def save_requirements(self, run_id: str, items: list[Requirement]) -> None:
        with self._connect() as connection:
            for item in items:
                snapshot = item.model_dump()
                connection.execute(
                    """
                    INSERT INTO requirements (
                        id, run_id, module, description, priority, acceptance,
                        prototype_element, related_steps_json, version, dirty, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        run_id,
                        item.module,
                        item.description,
                        item.priority,
                        item.acceptance,
                        item.prototype_element,
                        _json(item.related_steps),
                        item.version,
                        int(item.dirty),
                        _now(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO requirement_history
                        (requirement_id, run_id, version, snapshot_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item.id, run_id, item.version, _json(snapshot), _now()),
                )
            self._event(
                connection,
                run_id,
                "requirements.created",
                StageId.S5.value,
                "需求点已生成",
                {"count": len(items)},
            )

    def list_requirements(self, run_id: str) -> list[Requirement]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM requirements WHERE run_id = ? ORDER BY module, id", (run_id,)
            ).fetchall()
        return [
            Requirement(
                id=row["id"],
                module=row["module"],
                description=row["description"],
                priority=row["priority"],
                acceptance=row["acceptance"],
                prototype_element=row["prototype_element"],
                related_steps=json.loads(row["related_steps_json"]),
                version=row["version"],
                dirty=bool(row["dirty"]),
            )
            for row in rows
        ]

    def update_requirement(
        self, run_id: str, requirement_id: str, update: dict[str, Any]
    ) -> Requirement | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM requirements WHERE run_id = ? AND id = ?",
                (run_id, requirement_id),
            ).fetchone()
            if row is None:
                return None
            version = int(row["version"]) + 1
            snapshot = {
                "id": row["id"],
                "module": update["module"],
                "description": update["description"],
                "priority": update["priority"],
                "acceptance": update["acceptance"],
                "prototype_element": update["prototype_element"],
                "related_steps": json.loads(row["related_steps_json"]),
                "version": version,
                "dirty": True,
            }
            connection.execute(
                """
                UPDATE requirements SET module = ?, description = ?, priority = ?, acceptance = ?,
                    prototype_element = ?, version = ?, dirty = 1, updated_at = ?
                WHERE run_id = ? AND id = ?
                """,
                (
                    update["module"],
                    update["description"],
                    update["priority"],
                    update["acceptance"],
                    update["prototype_element"],
                    version,
                    _now(),
                    run_id,
                    requirement_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO requirement_history
                    (requirement_id, run_id, version, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (requirement_id, run_id, version, _json(snapshot), _now()),
            )
            self._event(
                connection,
                run_id,
                "requirement.updated",
                StageId.S5.value,
                "单条需求已修改；关联开发产物待重新生成",
                {"requirement_id": requirement_id, "version": version},
            )
        return Requirement.model_validate(snapshot)

    def add_knowledge(self, filename: str, file_type: str, content: str) -> dict[str, Any]:
        item_id = str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_items (id, filename, file_type, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (item_id, filename, file_type, content, timestamp),
            )
        return {
            "id": item_id,
            "filename": filename,
            "file_type": file_type,
            "enabled": True,
            "created_at": timestamp,
        }

    def list_knowledge(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, filename, file_type, enabled, created_at
                FROM knowledge_items WHERE deleted_at IS NULL ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def enabled_knowledge(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, filename, file_type, content FROM knowledge_items
                WHERE enabled = 1 AND deleted_at IS NULL ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_knowledge(self, item_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE knowledge_items SET deleted_at = ?, enabled = 0
                WHERE id = ? AND deleted_at IS NULL
                """,
                (_now(), item_id),
            )
        return cursor.rowcount > 0

    def set_knowledge_enabled(self, item_id: str, enabled: bool) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE knowledge_items SET enabled = ? WHERE id = ? AND deleted_at IS NULL",
                (int(enabled), item_id),
            )
        return cursor.rowcount > 0

    def add_skill(
        self,
        name: str,
        description: str,
        content: str,
        stages: list[StageId],
        enabled: bool = False,
    ) -> dict[str, Any]:
        item_id = str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO skills
                    (id, name, description, content, stages_json, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    name,
                    description,
                    content,
                    _json([stage.value for stage in stages]),
                    int(enabled),
                    timestamp,
                ),
            )
        return {
            "id": item_id,
            "name": name,
            "description": description,
            "stages": stages,
            "enabled": enabled,
            "created_at": timestamp,
        }

    def list_skills(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, stages_json, enabled, created_at FROM skills "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                **{key: row[key] for key in ("id", "name", "description", "enabled", "created_at")},
                "stages": json.loads(row["stages_json"]),
            }
            for row in rows
        ]

    def enabled_skills(self, stage: StageId) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT content, stages_json FROM skills WHERE enabled = 1")
            return [row["content"] for row in rows if stage.value in json.loads(row["stages_json"])]

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE skills SET enabled = ? WHERE id = ?", (int(enabled), skill_id)
            )
        return cursor.rowcount > 0

    def events_after(self, run_id: str, event_id: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND id > ? ORDER BY id",
                (run_id, event_id),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "stage": row["stage"],
                "message": row["message"],
                "detail": json.loads(row["detail_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        stage: str | None,
        message: str,
        detail: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO run_events (run_id, event_type, stage, message, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, event_type, stage, message, _json(detail), _now()),
        )
