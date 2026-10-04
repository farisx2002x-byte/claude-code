import io
import zipfile

import pytest

import config as C
from src import inputs, service

KML = '<kml>' + '<Placemark><name>a</name><Point><coordinates>39,21</coordinates></Point></Placemark>' * 3 + '</kml>'


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BUS_DATA_DIR", str(tmp_path / "in"))
    monkeypatch.setattr(C, "LOCAL_DATA", tmp_path / "data")
    monkeypatch.setattr(C, "SETTINGS_JSON", tmp_path / "settings.json")
    return tmp_path


def test_status_missing_then_upload(env):
    assert not any(s["found"] for s in inputs.status())
    assert "ملفات ناقصة" in service.missing_prereq("load")
    inputs.save_upload("students", io.BytesIO(KML.encode()))
    st = {s["key"]: s for s in inputs.status()}
    assert st["students"]["found"] and st["students"]["count"] == 3
    assert not st["students"]["ok"]            # المتوقع 8,729


def test_schools_zip_count(env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(4):
            z.writestr(f"s{i}.kml", "<kml/>")
    buf.seek(0)
    inputs.save_upload("schools", buf)
    assert {s["key"]: s for s in inputs.status()}["schools"]["count"] == 4


def test_set_data_dir_persists(env, monkeypatch):
    monkeypatch.delenv("BUS_DATA_DIR")
    monkeypatch.setattr(C, "SETTINGS_JSON", env / "settings.json")
    inputs.set_data_dir(env / "mine")
    assert C.resolve_data_dir() == env / "mine"


def test_prereq_for_later_steps(env, monkeypatch):
    monkeypatch.setattr(service, "dirs", lambda demo=False: (env / "w", env / "o"))
    assert "شغّل أولاً" in service.missing_prereq("routes")
    assert service.missing_prereq("routes", demo=True) is None
