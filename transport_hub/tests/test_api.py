import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSPORT_HUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TRANSPORT_HUB_API_KEYS", json.dumps({"v-key": "viewer", "a-key": "admin"}))
    import importlib

    import transport_hub.core.store as store

    importlib.reload(store)
    import transport_hub.api as api

    importlib.reload(api)
    return TestClient(api.app)


def H(k):
    return {"X-API-Key": k}


def test_health_open_but_data_requires_key(client):
    assert client.get("/health").status_code == 200
    assert client.get("/transit/routes").status_code == 401
    assert client.get("/transit/routes", headers=H("bad")).status_code == 401


def test_roles(client):
    assert client.post("/demo/load", headers=H("v-key")).status_code == 403
    assert client.post("/demo/load", headers=H("a-key")).status_code == 200


def test_missing_data_is_409_with_message(client):
    r = client.get("/taxi/kpis", headers=H("v-key"))
    assert r.status_code == 409 and "trips" in r.json()["detail"]


def test_endpoints_with_demo(client):
    client.post("/demo/load", headers=H("a-key"))
    r = client.get("/transit/routes", headers=H("v-key")).json()
    assert len(r) == 5 and r[0]["route_id"] == "R1"
    cov = client.get("/transit/coverage?radius=800", headers=H("v-key")).json()
    assert 50 < cov["kpis"]["covered_800_pct"] < 80
    s = client.post("/siting/max-coverage", json={"k": 5, "radius_m": 400}, headers=H("v-key")).json()
    assert len(s["sites"]) == 5 and s["coverage_after_pct"] > s["coverage_before_pct"]
    assert client.post("/siting/max-coverage", json={"k": 0}, headers=H("v-key")).status_code == 422
    assert client.get("/taxi/fleet?wait=3", headers=H("v-key")).json()["peak_vehicles"] > 0
    assert len(client.get("/admin/scorecard", headers=H("v-key")).json()) >= 8


def test_no_keys_configured_rejects(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSPORT_HUB_API_KEYS", raising=False)
    monkeypatch.setenv("TRANSPORT_HUB_WORKSPACE", str(tmp_path))
    import transport_hub.api as api

    assert TestClient(api.app).get("/datasets").status_code == 401


def test_report_package_endpoint(client):
    import io
    import zipfile

    assert client.post("/reports/package", headers=H("v-key")).status_code == 409  # لا بيانات بعد
    client.post("/demo/load", headers=H("a-key"))
    r = client.post("/reports/package?radius=500", headers=H("v-key"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert json.loads(zf.read("manifest.json"))["fingerprint"] == r.headers["x-fingerprint"]
    assert client.post("/reports/package").status_code == 401


def test_key_comparison_is_exact(client):
    assert client.get("/datasets", headers=H("v-key ")).status_code == 401
    assert client.get("/datasets", headers=H("V-KEY")).status_code == 401
    assert client.get("/datasets", headers=H("")).status_code == 401
    assert client.get("/datasets", headers=H("v-key")).status_code == 200
