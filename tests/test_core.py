from pathlib import Path

import pytest
from agent_elf.budget import BudgetExceeded, BudgetGuard
from agent_elf.models import Requirement
from agent_elf.store import StateStore


def test_budget_guard_rejects_call_before_budget_is_spent() -> None:
    with pytest.raises(BudgetExceeded):
        BudgetGuard.reserve(budget=20, spent=0, prompt="a prompt larger than the budget")


def test_artifacts_are_append_only_and_requirement_edits_are_versioned(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    run = store.create_run("A test product", 1_000)
    first = store.add_artifact(run["id"], "S4", "prototype_html", "<h1>draft</h1>")
    second = store.add_artifact(run["id"], "S4", "prototype_html", "<h1>revision</h1>")
    store.save_requirements(
        run["id"],
        [
            Requirement(
                id="REQ-1",
                module="Core",
                description="Initial description",
                priority="P0",
                acceptance="User can complete the main action.",
            )
        ],
    )

    updated = store.update_requirement(
        run["id"],
        "REQ-1",
        {
            "module": "Core",
            "description": "Revised description",
            "priority": "P0",
            "acceptance": "User can complete the revised main action.",
            "prototype_element": "Main action button",
        },
    )

    assert first["version"] == 1
    assert second["version"] == 2
    assert second["parent_version"] == 1
    assert [artifact["content"] for artifact in store.list_artifacts(run["id"])] == [
        "<h1>draft</h1>",
        "<h1>revision</h1>",
    ]
    assert updated is not None
    assert updated.version == 2
    assert updated.dirty is True
    assert len(store.list_requirements(run["id"])) == 1
