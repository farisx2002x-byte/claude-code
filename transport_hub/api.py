"""واجهة REST للمنصة (خدمة جانبية): تشغيل  uvicorn transport_hub.api:app

الأمان: مفاتيح API من متغير البيئة TRANSPORT_HUB_API_KEYS كـ JSON مثل {"مفتاح-المشاهد":"viewer","مفتاح-المدير":"admin"}
الترويسة: X-API-Key. بدون ضبط المفاتيح كل المسارات (عدا /health) ترفض الطلب. المشاهد يقرأ فقط، والمدير يعدّل."""

import hmac
import json
import os

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from transport_hub.core import geo
from transport_hub.core.store import Workspace

app = FastAPI(title="Transport Hub API", version="1.0")


def _keys():
    try:
        return json.loads(os.environ.get("TRANSPORT_HUB_API_KEYS", "{}"))
    except Exception:
        return {}


def _role_of(key):
    """دور المفتاح بمقارنة بزمن ثابت (يمنع استنتاج المفتاح من زمن الاستجابة)."""
    found = None
    for k, role in _keys().items():
        if hmac.compare_digest(k.encode(), (key or "").encode()):
            found = role
    return found


def auth(role="viewer"):
    def dep(x_api_key: str = Header(default="")):
        r = _role_of(x_api_key)
        if r is None:
            raise HTTPException(401, "مفتاح API غير صالح أو غير مضبوط")
        if role == "admin" and r != "admin":
            raise HTTPException(403, "هذه العملية تحتاج صلاحية مدير")
        return r

    return dep


def ws():
    return Workspace()


def _need(*names):
    w = ws()
    out = {}
    for n in names:
        v = w.df(n)
        v = v if v is not None else w.obj(n)
        if v is None:
            raise HTTPException(409, f"البيانات ناقصة: {n}. حمّلها أولاً (واجهة المنصة أو POST /demo/load)")
        out[n] = v
    return out


def _feed():
    from transport_hub.transit import gtfs

    return gtfs.from_tables(_need("gtfs")["gtfs"])


def _proj():
    return geo.Projector(_need("proj_epsg")["proj_epsg"])


def _access():
    from transport_hub.core.access import load_access

    return load_access(ws())


def _clean(o):
    """يحوّل نتائج numpy/pandas لقيم JSON."""
    import pandas as pd

    if isinstance(o, pd.DataFrame):
        return json.loads(o.replace([np.inf, -np.inf], None).to_json(orient="records", force_ascii=False))
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (np.floating, float)):
        return None if (np.isnan(o) or np.isinf(o)) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


@app.get("/health")
def health():
    return {"status": "ok", "datasets": [k for k in ws().meta() if not k.startswith("_")]}


@app.get("/datasets", dependencies=[Depends(auth())])
def datasets():
    return ws().meta()


@app.post("/demo/load", dependencies=[Depends(auth("admin"))])
def demo_load():
    from transport_hub.core import data as D
    from transport_hub.core import demo_city

    w, d = ws(), demo_city.build_all()
    p = geo.Projector.for_points(d["population"].lon, d["population"].lat)
    w.save_obj("proj_epsg", p.epsg)
    w.save_df("population", D.clean_population(d["population"], p))
    w.save_df("poi", D.clean_poi(d["poi"], p))
    w.save_obj("gtfs", d["gtfs"])
    w.save_df("trips", D.clean_trips(d["trips"], p))
    w.save_df("stands", p.attach(d["stands"]))
    w.save_obj("roads_lines", demo_city.street_lines())
    for k in ("population", "poi", "gtfs", "trips", "stands", "roads_lines"):
        w.set_source(k, "demo")
    w.log("demo_loaded_api")
    return {"loaded": True}


@app.post("/reports/package", dependencies=[Depends(auth())])
def reports_package(radius: int = 400):
    """حزمة المخرجات الموثّقة (zip: Excel + تقرير HTML + GIS + manifest) من بيانات مساحة العمل."""
    from fastapi.responses import Response

    from transport_hub.exports import builder

    try:
        data, meta = builder.build_package(ws(), radius=radius)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="transport_package_{meta["fingerprint"]}.zip"', "X-Fingerprint": meta["fingerprint"]},
    )


@app.get("/transit/routes", dependencies=[Depends(auth())])
def transit_routes():
    from transport_hub.transit import service

    return _clean(service.route_metrics(_feed(), proj=_proj(), access=_access()))


@app.get("/transit/coverage", dependencies=[Depends(auth())])
def transit_coverage(radius: int = 400):
    from transport_hub.transit import coverage as COV
    from transport_hub.transit import planning, service

    pop, feed, proj = _need("population")["population"], _feed(), _proj()
    st = COV.stops_frame(feed, proj)
    k, cov = planning.scenario_kpis(pop, st, service.stop_route_freq(feed), radii=(radius,), access=_access())
    return _clean({"kpis": k, "by_district": COV.summary(cov)})


class SitingReq(BaseModel):
    k: int = Field(10, ge=1, le=200)
    radius_m: int = Field(400, ge=50, le=5000)
    cell_m: int = Field(250, ge=100, le=1000)


@app.post("/siting/max-coverage", dependencies=[Depends(auth())])
def siting_max_coverage(req: SitingReq):
    from transport_hub.transit import coverage as COV
    from transport_hub.transit import planning

    pop, proj = _need("population")["population"], _proj()
    ex = None
    w = ws().obj("gtfs")
    if w is not None:
        ex = COV.stops_frame(_feed(), proj)[["x", "y"]].to_numpy()
    cand = geo.candidate_grid(pop["x"], pop["y"], req.cell_m)
    sel, (b, a) = planning.suggest_stops(pop, ex if ex is not None else np.zeros((0, 2)), cand, req.radius_m, req.k, proj=proj, access=_access())
    return _clean({"coverage_before_pct": b, "coverage_after_pct": a, "sites": sel[["rank", "gain", "cum_covered_pct", "lon", "lat"]]})


@app.get("/taxi/kpis", dependencies=[Depends(auth())])
def taxi_kpis():
    from transport_hub.taxi import fleet

    return _clean(fleet.kpis(_need("trips")["trips"]))


@app.get("/taxi/fleet", dependencies=[Depends(auth())])
def taxi_fleet(wait: float = 5.0, util: float = 0.75):
    from transport_hub.taxi import fleet

    fh = fleet.fleet_by_hour(_need("trips")["trips"], wait, 6.0, util)
    return _clean({"peak_vehicles": int(fh["needed"].max()), "by_hour": fh})


@app.get("/admin/scorecard", dependencies=[Depends(auth())])
def scorecard():
    from transport_hub.admin import equity
    from transport_hub.admin import scorecard as SC
    from transport_hub.transit import coverage as COV
    from transport_hub.transit import planning, service

    pop, feed, proj = _need("population")["population"], _feed(), _proj()
    st = COV.stops_frame(feed, proj)
    acc = _access()
    k, cov = planning.scenario_kpis(pop, st, service.stop_route_freq(feed), access=acc)
    rm = service.route_metrics(feed, proj=proj, access=acc)
    vals = dict(
        transit_cov400=k["covered_400_pct"],
        transit_cov800=k["covered_800_pct"],
        transit_ai=k["avg_access_index"],
        transit_headway=float(rm["peak_headway_min"].mean()),
        transit_no_service=100 * k["pop_no_service"] / pop["pop"].sum(),
        equity_gini=equity.gini(cov["access_index"], cov["pop"]),
    )
    return _clean(SC.build(vals).drop(columns="key"))
