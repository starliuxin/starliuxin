from __future__ import annotations

import time
from pathlib import Path

from agent_elf.app import create_app
from agent_elf.provider import ChatResult, DemoProvider
from fastapi.testclient import TestClient


def wait_for_status(client: TestClient, run_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 15
    latest = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest["status"] == expected:
            return latest
        if latest["status"] in {"FAILED", "CANCELLED"}:
            raise AssertionError(f"Run ended unexpectedly: {latest}")
        time.sleep(0.03)
    raise AssertionError(f"Run did not reach {expected}: {latest}")


def test_full_demo_run_pauses_for_both_human_gates(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workflow.sqlite3", DemoProvider())
    with TestClient(app) as client:
        created = client.post(
            "/api/runs",
            json={"user_input": "做一个帮助自由职业者跟踪账单的工具", "token_budget": 200_000},
        )
        assert created.status_code == 202
        run_id = created.json()["id"]

        s5 = wait_for_status(client, run_id, "WAITING_HUMAN")
        assert s5["current_stage"] == "S5"
        assert s5["plan"]["final_goal"]
        assert [step["stage"] for step in s5["plan"]["steps"]] == [
            "S1",
            "S2",
            "S3",
            "S4",
            "S5",
            "S6",
            "S7",
            "S8",
        ]

        requirements = client.get(f"/api/runs/{run_id}/requirements").json()
        assert len(requirements) == 2
        update = client.put(
            f"/api/runs/{run_id}/requirements/{requirements[0]['id']}",
            json={
                "module": requirements[0]["module"],
                "description": "经人工修改的需求描述",
                "priority": requirements[0]["priority"],
                "acceptance": requirements[0]["acceptance"],
                "prototype_element": requirements[0]["prototype_element"],
            },
        )
        assert update.status_code == 200
        assert update.json()["dirty"] is True
        assert update.json()["version"] == 2

        continued = client.post(
            f"/api/runs/{run_id}/resume",
            json={"decision": "continue", "comment": "确认需求"},
        )
        assert continued.status_code == 200
        s8 = wait_for_status(client, run_id, "WAITING_HUMAN")
        assert s8["current_stage"] == "S8"

        artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()
        stage_five = [artifact for artifact in artifacts if artifact["stage"] == "S5"]
        assert len(stage_five) == 1
        prototype = next(item for item in artifacts if item["kind"] == "prototype_html")
        assert "<html" in prototype["content"]
        report = next(item for item in artifacts if item["kind"] == "static_report")
        assert '"execution_status": "not_run"' in report["content"]
        assert "test_cases" not in report["content"] or '"status": "not_run"' in report["content"]
        safety = next(item for item in artifacts if item["stage"] == "S8")
        assert "未应用、未部署" in safety["content"]

        completed = client.post(
            f"/api/runs/{run_id}/resume",
            json={"decision": "approve_review", "comment": "已阅读，未应用"},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "COMPLETED"
        events = client.get(f"/api/runs/{run_id}/log").json()
        assert any(event["event_type"] == "model.usage" for event in events)
        assert any(event["event_type"] == "artifact.created" for event in events)
        stream = client.get(f"/api/runs/{run_id}/events?after_id=0")
        assert "data:" in stream.text
        last_event_id = events[-1]["id"]
        replay = client.get(
            f"/api/runs/{run_id}/events?after_id=0",
            headers={"Last-Event-ID": str(last_event_id)},
        )
        assert "data:" not in replay.text


def test_token_budget_must_be_increased_before_resuming(tmp_path: Path) -> None:
    app = create_app(tmp_path / "budget.sqlite3", DemoProvider())
    with TestClient(app) as client:
        response = client.post(
            "/api/runs",
            json={"user_input": "短产品需求", "token_budget": 1},
        )
        assert response.status_code == 202
        run_id = response.json()["id"]
        paused = wait_for_status(client, run_id, "PAUSED")
        assert paused["total_tokens"] == 0

        rejected = client.post(
            f"/api/runs/{run_id}/resume",
            json={"decision": "continue"},
        )
        assert rejected.status_code == 409
        assert "必须同时增加 token 上限" in rejected.json()["detail"]

        resumed = client.post(
            f"/api/runs/{run_id}/resume",
            json={"decision": "continue", "additional_token_budget": 100_000},
        )
        assert resumed.status_code == 200
        s5 = wait_for_status(client, run_id, "WAITING_HUMAN")
        assert s5["token_budget"] == 100_001


class ExternalStub:
    name = "test-provider"
    model = "test-model"

    async def complete(self, *, system: str, prompt: str, max_output_tokens: int) -> ChatResult:
        return ChatResult("{}", 1, 1, 1, "test-model")


def test_external_provider_requires_explicit_data_disclosure_ack(tmp_path: Path) -> None:
    app = create_app(tmp_path / "external.sqlite3", ExternalStub())
    with TestClient(app) as client:
        settings = client.get("/api/settings")
        assert settings.status_code == 200
        assert settings.json()["external_data_disclosure"]

        response = client.post(
            "/api/runs",
            json={"user_input": "A product idea", "token_budget": 1_000},
        )
        assert response.status_code == 400
        assert "必须确认" in response.json()["detail"]


def test_knowledge_rejects_unsupported_types_and_skills_start_disabled(tmp_path: Path) -> None:
    app = create_app(tmp_path / "capabilities.sqlite3", DemoProvider())
    with TestClient(app) as client:
        rejected = client.post(
            "/api/knowledge",
            json={"filename": "https://example.com/data.csv", "content": "not fetched"},
        )
        assert rejected.status_code == 400

        imported = client.post(
            "/api/knowledge",
            json={"filename": "notes.md", "content": "local note"},
        )
        assert imported.status_code == 201
        assert imported.json()["filename"] == "notes.md"
        toggled = client.put(
            f"/api/knowledge/{imported.json()['id']}",
            json={"enabled": False},
        )
        assert toggled.status_code == 200
        assert toggled.json()["enabled"] is False

        skill = client.post(
            "/api/skills",
            json={
                "name": "Plain prompt",
                "description": "Text-only instruction",
                "content": "Keep the output concise.",
                "stages": ["S4"],
            },
        )
        assert skill.status_code == 201
        assert skill.json()["enabled"] is False

        enabled_on_import = client.post(
            "/api/skills",
            json={
                "name": "Unsafe default",
                "description": "Should not enable on import",
                "content": "Text",
                "stages": ["S4"],
                "enabled": True,
            },
        )
        assert enabled_on_import.status_code == 422
