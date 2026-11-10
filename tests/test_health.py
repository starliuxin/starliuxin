from pathlib import Path

from agent_elf.app import create_app
from agent_elf.provider import DemoProvider
from fastapi.testclient import TestClient


def test_health_endpoint(tmp_path: Path) -> None:
    app = create_app(tmp_path / "health.sqlite3", DemoProvider())
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agent-elf"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
