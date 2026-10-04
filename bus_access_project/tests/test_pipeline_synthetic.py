"""اختبار شامل على بيانات اصطناعية: load→tiles→network→score→routes→export بدون أي بيانات حقيقية."""
import argparse
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

import config as C

OX, OY = 520000.0, 2384000.0   # بداية مربع (مضاعف 2000) قرب جدة


def make_data(work):
    rng = np.random.default_rng(1)
    polys = []
    for i in range(8):
        for j in range(5):
            x, y = OX + i * 74, OY + 40 + j * 74
            polys.append(box(x, y, x + 60, y + 60))
    polys.append(box(OX - 100, OY, OX + 800, OY + 7))
    polys.append(box(OX - 100, OY + 33, OX + 800, OY + 40))
    parcels = gpd.GeoDataFrame({"LU_ZONE": ["سكني"] * len(polys)}, geometry=polys, crs=C.CRS_UTM)
    parcels.to_parquet(work / "parcels.parquet")
    roads = gpd.GeoDataFrame({"fclass": ["primary"], "oneway": ["B"]},
                             geometry=[LineString([(OX - 100, OY + 20), (OX + 800, OY + 20)])], crs=C.CRS_UTM)
    roads.to_parquet(work / "roads.parquet")
    dist = gpd.GeoDataFrame({"ARNAME": ["حي تجريبي"]}, geometry=[box(OX - 50, OY - 50, OX + 700, OY + 450)], crs=C.CRS_UTM)
    dist.to_parquet(work / "districts.parquet")
    rows = []
    for k in range(120):
        sx = OX + 67 + 74 * rng.integers(0, 7) + rng.uniform(-3, 3)
        sy = OY + rng.uniform(50, 380)
        rows.append(dict(idx=k, name=f"طالب {k}", sid=str(k), school="مدرسة أ" if k % 2 else "مدرسة ب",
                         stage=["ابتدائي", "متوسط", "ثانوي"][k % 3], guardian="", phone="", address="",
                         lon=39.2, lat=21.5, x=sx, y=sy))
    pd.DataFrame(rows).to_parquet(work / "students.parquet")
    pd.DataFrame([dict(name="مدرسة أ", lon=0, lat=0, x=OX + 67 + 74, y=OY + 107 + 74),
                  dict(name="مدرسة ب", lon=0, lat=0, x=OX + 67 + 222, y=OY + 107 + 148)]).to_parquet(work / "schools.parquet")


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
    pd.DataFrame({"student_school": ["مدرسة أ", "مدرسة ب"], "official_name": ["مدرسة أ", "مدرسة ب"],
                  "match": ["exact", "exact"]}).to_csv(data / "school_lookup.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"اسم المدرسة": ["مدرسة أ", "مدرسة ب"], "المقاعد": [72, 26], "النوع": ["G9", "COUNTY"],
                  "اسم السائق": ["س", "ص"]}).to_excel(tmp_path / "fleet.xlsx", index=False)
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
