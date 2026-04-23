from fastapi.testclient import TestClient

from deepflow_analyst.main import app

client = TestClient(app)


def test_health_endpoint_returns_200() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "db" in data


def test_query_endpoint_never_crashes() -> None:
    """The endpoint must always return 200 — pipeline errors surface via the
    `status` and `error` fields, not as an HTTP 500."""
    resp = client.post("/api/query", json={"question": "show artists"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "error")
    if data["status"] == "error":
        assert data["error"]
