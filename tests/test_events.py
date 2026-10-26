from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import create_app


def payload():
    return {"title": "Cloud Computing Workshop", "venue": "Lab 1", "capacity": 2,
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}


def test_catalogue(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'events.db'}")) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        result = client.post("/events", json=payload())
        assert result.status_code == 201
        event = result.json()
        assert client.get(f"/events/{event['id']}").json()["capacity"] == 2
        assert len(client.get("/events").json()) == 1
        assert client.get("/events?limit=0").status_code == 422
        assert client.get("/events/missing").status_code == 404


def test_validation_and_persistence(tmp_path):
    url = f"sqlite:///{tmp_path / 'persistent.db'}"
    with TestClient(create_app(url)) as client:
        for changes in ({"capacity": 0}, {"title": " "}, {"starts_at": "2020-01-01T00:00:00Z"},
                        {"starts_at": "2099-01-01T00:00:00"}):
            assert client.post("/events", json=payload() | changes).status_code == 422
        event = client.post("/events", json=payload()).json()
    with TestClient(create_app(url)) as client:
        response = client.get(f"/events/{event['id']}")
        assert response.status_code == 200
        assert response.json()["starts_at"].endswith("Z")
