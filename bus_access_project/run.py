"""تشغيل خطوات التحليل:  python run.py <step> [--workers N] [--fresh]
الخطوات: all, load, tiles, network, score, routes, scenarios, export, report"""
import argparse
import json
import pickle
import sys
import time
from datetime import datetime

import geopandas as gpd
import numpy as np
import pandas as pd

import config as C


class Tee:
    """يكتب كل ما يطبع في الشاشة وفي output/سجل_التشغيل.txt."""
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")
        self.o = sys.stdout

    def write(self, s):
        self.o.write(s)
        self.f.write(s)

    def flush(self):
        self.o.flush()
        self.f.flush()


def _save(name, obj):
    C.WORK.mkdir(exist_ok=True)
    pickle.dump(obj, open(C.WORK / name, "wb"))


def _load(name):
    return pickle.load(open(C.WORK / name, "rb"))


def step_load(a):
    from src import load_data
    load_data.load_all()


def step_tiles(a):
    from src import run_tiles
    st = pd.read_parquet(C.WORK / "students.parquet")
    sc = pd.read_parquet(C.WORK / "schools.parquet")
    raw, streets, obst = run_tiles.run(st, sc, a.workers, a.fresh)
    _save("res_raw.pkl", (raw, streets, obst))
    print(f"طلاب: {len(raw):,} | مقاطع شوارع: {len(streets):,} | عوائق: {len(obst):,}")


def step_network(a):
    from src import network
    _, streets, _ = _load("res_raw.pkl")
    roads = gpd.read_parquet(C.WORK / "roads.parquet")
    net = network.build_network(streets, roads)
    net.save(C.WORK / "network.pkl")
    print(f"الشبكة: {net.n:,} عقدة، {len(net.u):,} ضلع، {net.length.sum() / 2000:,.0f} كم")


def step_score(a):
    from src import fleet, load_data, score, validate
    raw, streets, obst = _load("res_raw.pkl")
    parcels = gpd.read_parquet(C.WORK / "parcels.parquet")
    districts = gpd.read_parquet(C.WORK / "districts.parquet")
    schools = pd.read_parquet(C.WORK / "schools.parquet")
    df = score.attach_geo(raw, parcels, districts)
    df = score.score_all(df)
    df = score.link_schools(df, schools, load_data.load_lookup())
    df, pickups = score.build_pickups(df, "large")
    df = score.attach_board_point(df)
    fl = fleet.read_fleet()
    byschool = fleet.by_school(df, fl)
    q = validate.check(df)
    _save("res_scored.pkl", dict(df=df, pickups=pickups, fleet=byschool, quality=q))
    vc = df["level_L"].value_counts()
    print("الكبير:", {k: int(vc.get(k, 0)) for k in score.LEVELS})
    print("الموصى بها:", df["rec_vehicle"].value_counts().to_dict(), "| نقاط التجميع:", len(pickups))
    print("الأسطول:", len(fl), "حافلة")


def step_routes(a):
    from src import export_routes, network, ops, routes
    S = _load("res_scored.pkl")
    df = S["df"]
    net = network.Network.load(C.WORK / "network.pkl")
    schools = pd.read_parquet(C.WORK / "schools.parquet")
    sxy = dict(zip(schools["name"], zip(schools.x, schools.y)))
    df = df.reset_index(drop=True)
    df["road_min"], df["road_km"] = network.school_times(net, df, sxy)
    print(f"زمن الطريق المباشر: وسيط {np.nanmedian(df.road_min):.0f} د")
    R, RS, SA, G, nores, _ = routes.plan_all(df, net, sxy, save=True)
    _save("routes.pkl", dict(R=R, RS=RS, SA=SA, G=G, nores=nores))
    S["df"] = df
    _save("res_scored.pkl", S)
    print(f"مسارات: {len(R)} | {ops.totals(R, len(SA))} | بدون مسار: {len(nores)}")
    do_export()


def step_scenarios(a):
    from src import network, scenarios
    S = _load("res_scored.pkl")
    net = network.Network.load(C.WORK / "network.pkl")
    schools = pd.read_parquet(C.WORK / "schools.parquet")
    sxy = dict(zip(schools["name"], zip(schools.x, schools.y)))
    sc = scenarios.run(S["df"], net, sxy)
    _save("scenarios.pkl", sc)
    print(sc.to_string(index=False))
    do_export()


def do_export():
    """يكتب كل المخرجات من الحالة المحفوظة في work/ (المسارات والسيناريوهات اختيارية)."""
    from src import export_excel, export_gis, export_routes, export_webmap, ops
    C.OUTPUT.mkdir(exist_ok=True)
    S = _load("res_scored.pkl")
    df, pickups = S["df"].copy(), S["pickups"]
    raw, streets, obst = _load("res_raw.pkl")
    schools = pd.read_parquet(C.WORK / "schools.parquet")
    districts = gpd.read_parquet(C.WORK / "districts.parquet")
    rt = _load("routes.pkl") if (C.WORK / "routes.pkl").exists() else None
    sc = _load("scenarios.pkl") if (C.WORK / "scenarios.pkl").exists() else None
    rg = sg = None
    sops = None
    if rt is not None:
        a = rt["SA"].set_index("idx")
        for c in ("route", "board_time", "ride_min"):
            df[c] = df["idx"].map(a[c])
        rg, sg = export_routes.gis_layers(rt["R"], rt["RS"], rt["G"])
        sops = ops.school_ops(rt["R"], S["fleet"])
    export_gis.write_gpkg(C.OUTPUT / "تحليل_وصول_الباص.gpkg", df, streets, obst, pickups, schools, rg, sg)
    export_gis.write_students_kml(C.OUTPUT / "وصول_الباص_للطلاب.kml", df, pickups, obst)
    export_excel.write_excel(C.OUTPUT / "تحليل_وصول_الباص.xlsx", df, None, None, pickups, S["fleet"], S["quality"],
                             sops, sc)
    export_webmap.build(df, pickups, obst, schools, districts, streets, C.OUTPUT / "خريطة_وصول_الباص.html")
    if rt is not None:
        export_routes.write_routes_kml(C.OUTPUT / "مسارات_الباصات.kml", rt["R"], rt["RS"], rt["G"])
        export_routes.write_driver_sheets(C.OUTPUT / "جداول_السائقين.xlsx", rt["R"], rt["RS"], rt["SA"], df, rt["nores"])
    manifest = dict(version=C.VERSION, time=datetime.now().isoformat(timespec="seconds"), students=len(df),
                    files=sorted(p.name for p in C.OUTPUT.iterdir()))
    (C.OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("تم التصدير:", ", ".join(manifest["files"]))


def step_report(a):
    step_score(a)
    do_export()


STEPS = {"load": step_load, "tiles": step_tiles, "network": step_network, "score": step_score,
         "routes": step_routes, "scenarios": step_scenarios, "export": lambda a: do_export(), "report": step_report}
ALL = ["load", "tiles", "network", "score", "routes"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["all"] + list(STEPS))
    ap.add_argument("--workers", type=int, default=C.WORKERS)
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args(argv)
    C.OUTPUT.mkdir(exist_ok=True)
    sys.stdout = Tee(C.OUTPUT / "سجل_التشغيل.txt")
    print(f"\n=== {datetime.now():%Y-%m-%d %H:%M} | الإصدار {C.VERSION} | {a.step} ===")
    for s in (ALL if a.step == "all" else [a.step]):
        t0 = time.time()
        print(f"--- {s} ---")
        STEPS[s](a)
        print(f"({s}: {time.time() - t0:.0f} ث)")


if __name__ == "__main__":
    main()
