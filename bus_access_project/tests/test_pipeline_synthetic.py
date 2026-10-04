"""اختبار شامل على بيانات اصطناعية: load→tiles→network→score→routes→export بدون أي بيانات حقيقية."""
import argparse
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

import config as C

from src.demo_data import make_data


@pytest.fixture()
def env(tmp_path, monkeypatch):
    work, out, data = tmp_path / "work", tmp_path / "output", tmp_path / "data"
    for d in (work, out, data):
        d.mkdir()
    monkeypatch.setattr(C, "WORK", work)
    monkeypatch.setattr(C, "OUTPUT", out)
    monkeypatch.setattr(C, "LOCAL_DATA", data)
    monkeypatch.setattr(C, "SCHOOL_LOOKUP", data / "school_lookup.csv")
    monkeypatch.setattr(C, "FLEET_ALIAS", data / "fleet_alias.csv")
    monkeypatch.setattr(C, "FLEET_XLSX", tmp_path / "fleet.xlsx")
    monkeypatch.setattr(C, "VRP_TIME_MIN", 2)
    monkeypatch.setattr(C, "VRP_TIME_MAX", 3)
    make_data(work)
    from src.demo_data import make_side_files
    make_side_files(data, tmp_path / "fleet.xlsx", data / "school_lookup.csv")
    return work, out


def test_full_pipeline(env):
    import run
    work, out = env
    a = argparse.Namespace(workers=1, fresh=False)
    run.step_tiles(a)
    run.step_network(a)
    run.step_score(a)
    S = run._load("res_scored.pkl")
    df = S["df"]
    assert len(df) == 120
    assert df["rec_vehicle"].notna().all()
    assert df["reasons_L"].str.len().gt(0).all()
    # أغلب الطلاب في شوارع 14 م: الكبير يوصلهم أو فيه نتيجة معقولة
    assert (df.level_L == "سهل").mean() > 0.5
    run.step_routes(a)
    rt = run._load("routes.pkl")
    assigned = set(rt["SA"]["idx"]) | set(rt["nores"])
    assert assigned == set(df["idx"])
    assert (rt["R"].students <= rt["R"].seats * C.LOAD_FACTOR + 1).all()
    for f in ("تحليل_وصول_الباص.gpkg", "تحليل_وصول_الباص.xlsx", "وصول_الباص_للطلاب.kml",
              "خريطة_وصول_الباص.html", "مسارات_الباصات.kml", "جداول_السائقين.xlsx", "manifest.json"):
        assert (out / f).exists(), f
    # الخريطة بدون أسماء أو أرقام طلاب
    html = (out / "خريطة_وصول_الباص.html").read_text(encoding="utf-8")
    assert "طالب 5" not in html and "طالب 17" not in html
    kml = (out / "مسارات_الباصات.kml").read_text(encoding="utf-8")
    assert "طالب 5<" not in kml
    # GPKG بالطبقات المتوقعة
    layers = gpd.list_layers(out / "تحليل_وصول_الباص.gpkg")["name"].tolist()
    for l in ("students_access", "streets_bus_width", "schools", "bus_routes", "route_stops"):
        assert l in layers
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["version"] == C.VERSION
