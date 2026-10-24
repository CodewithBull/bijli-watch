import pytest

flask = pytest.importorskip("flask")  # server tests need Flask installed

from server.app import app, store  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_health(client):
    assert client.get("/health").get_json()["status"] == "ok"


def test_post_and_list_readings(client):
    resp = client.post("/readings", json={
        "voltage_v": 230.0, "current_a": 2.0, "energy_kwh": 10.0,
    })
    assert resp.status_code == 201
    body = resp.get_json()["reading"]
    assert body["power_w"] == 460.0  # derived from V x A

    listed = client.get("/readings").get_json()
    assert listed["count"] == 1


def test_post_reading_validation(client):
    assert client.post("/readings", json={}).status_code == 400
    assert client.post("/readings", data="not json",
                       content_type="application/json").status_code == 400
    assert client.post("/readings", json={"power_w": -5}).status_code == 400


def test_summary_and_dashboard(client):
    client.post("/readings", json={"power_w": 6000, "energy_kwh": 50.0})
    summary = client.get("/summary").get_json()
    assert summary["reading_count"] == 1
    assert summary["has_active_spike"] is True  # 6000 W > 4000 W default

    html = client.get("/").get_data(as_text=True)
    assert "bijli-watch" in html
    assert "/summary" in html  # fallback link is present in the page
