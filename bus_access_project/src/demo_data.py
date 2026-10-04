"""بيانات تجريبية اصطناعية (حي صغير بشوارع 14 م وزقاق مسدود) لعرض الواجهة والتأكد من التشغيل بدون بيانات حقيقية.
الاستخدام:  BUS_DEMO_DIR=demo_state python -m src.demo_data      (أو من زر «تجربة» في الواجهة)
ما تلمس البيانات الحقيقية: كل شيء يُكتب داخل مجلد التجربة."""
import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, box

OX, OY = 520000.0, 2384000.0   # بداية مربع (مضاعف 2000) قرب جدة


def make_data(work, n_students=120, seed=1):
    import config as C
    rng = np.random.default_rng(seed)
    polys = [box(OX + i * 74, OY + 40 + j * 74, OX + i * 74 + 60, OY + 40 + j * 74 + 60) for i in range(8) for j in range(5)]
    polys += [box(OX - 100, OY, OX + 800, OY + 7), box(OX - 100, OY + 33, OX + 800, OY + 40)]
    gpd.GeoDataFrame({"LU_ZONE": ["سكني"] * len(polys)}, geometry=polys, crs=C.CRS_UTM).to_parquet(work / "parcels.parquet")
    gpd.GeoDataFrame({"fclass": ["primary"], "oneway": ["B"]},
                     geometry=[LineString([(OX - 100, OY + 20), (OX + 800, OY + 20)])], crs=C.CRS_UTM).to_parquet(work / "roads.parquet")
    gpd.GeoDataFrame({"ARNAME": ["حي تجريبي"]}, geometry=[box(OX - 50, OY - 50, OX + 700, OY + 450)],
                     crs=C.CRS_UTM).to_parquet(work / "districts.parquet")
    rows = []
    for k in range(n_students):
        rows.append(dict(idx=k, name=f"طالب {k}", sid=str(k), school="مدرسة أ" if k % 2 else "مدرسة ب",
                         stage=["ابتدائي", "متوسط", "ثانوي"][k % 3], guardian="", phone="", address="", lon=39.2, lat=21.5,
                         x=OX + 67 + 74 * rng.integers(0, 7) + rng.uniform(-3, 3), y=OY + rng.uniform(50, 380)))
    pd.DataFrame(rows).to_parquet(work / "students.parquet")
    pd.DataFrame([dict(name="مدرسة أ", lon=0, lat=0, x=OX + 67 + 74, y=OY + 107 + 74),
                  dict(name="مدرسة ب", lon=0, lat=0, x=OX + 67 + 222, y=OY + 107 + 148)]).to_parquet(work / "schools.parquet")


def make_side_files(data_dir, fleet_xlsx, lookup_csv):
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"student_school": ["مدرسة أ", "مدرسة ب"], "official_name": ["مدرسة أ", "مدرسة ب"],
                  "match": ["exact", "exact"]}).to_csv(lookup_csv, index=False, encoding="utf-8-sig")
    pd.DataFrame({"اسم المدرسة": ["مدرسة أ", "مدرسة ب"], "المقاعد": [72, 26], "النوع": ["G9", "COUNTY"]}).to_excel(fleet_xlsx, index=False)


def main():
    if not os.environ.get("BUS_DEMO_DIR"):
        sys.exit("شغّله مع BUS_DEMO_DIR (مجلد منفصل) عشان ما يلمس البيانات الحقيقية")
    import config as C
    for d in (C.WORK, C.OUTPUT, C.LOCAL_DATA):
        d.mkdir(parents=True, exist_ok=True)
    C.VRP_TIME_MIN, C.VRP_TIME_MAX = 2, 3
    make_data(C.WORK)
    make_side_files(C.LOCAL_DATA, C.FLEET_XLSX, C.SCHOOL_LOOKUP)
    import run
    a = argparse.Namespace(workers=1, fresh=False)
    for step in (run.step_tiles, run.step_network, run.step_score, run.step_routes):
        step(a)
    print("جاهز: بيانات تجريبية في", C.WORK.parent)


if __name__ == "__main__":
    main()
