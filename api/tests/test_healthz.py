from fastapi.testclient import TestClient

from api.main import app


def test_healthz_is_ok_without_a_database() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body == {"status": "ok", "seeded": False}
