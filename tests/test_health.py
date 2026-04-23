from fastapi.testclient import TestClient

from deepflow_analyst.main import app

client = TestClient(app)


def test_health_endpoint_returns_200() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "db" in data


def test_query_endpoint_stub() -> None:
    resp = client.post("/api/query", json={"question": "show me top 10 customers"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_implemented"
    assert "top 10 customers" in data["answer"]
