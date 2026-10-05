import json

import numpy as np
import pandas as pd
import pytest

from transport_hub.core import demo_city as DC
from transport_hub.core import geo
from transport_hub.core.access import Access, load_access
from transport_hub.core.roadnet import (
    Lines,
    RoadDataError,
    RoadNetwork,
    _oneway_code,
    _speed,
    from_geojson,
    from_overpass,
    overpass_query,
    read_roads,
)
from transport_hub.core.store import Workspace

PROJ = geo.Projector(32637)
X0, Y0 = 520000.0, 2384000.0


def lines_xy(segs, fclass="residential", oneway="B"):
    """خطوط من إحداثيات مسقطة بالمتر (نسبة لنقطة أصل) → Lines بـ lon/lat."""
    co = []
    for s in segs:
        a = np.asarray(s, float)
        lo, la = PROJ.lonlat(X0 + a[:, 0], Y0 + a[:, 1])
        co.append(np.column_stack([lo, la]))
    n = len(co)
    return Lines(co, [fclass] * n, [oneway] * n if isinstance(oneway, str) else list(oneway), [np.nan] * n)


def grid(n=5, step=100.0, **kw):
    segs = []
    for i in range(n):
        segs.append([(i * step, j * step) for j in range(n)])
        segs.append([(j * step, i * step) for j in range(n)])
    return lines_xy(segs, **kw)


def pt(x, y):
    return np.array([[X0 + x, Y0 + y]])


# ───────── قراءة الصيغ ─────────
def test_oneway_and_speed_parsing():
    assert [_oneway_code(v) for v in ("F", "yes", "1", "true", "T", "-1", "B", "no", "", None)] == ["F", "F", "F", "F", "T", "T", "B", "B", "B", "B"]
    assert _speed("50") == 50 and abs(_speed("30 mph") - 48.27) < 0.1 and np.isnan(_speed("walk")) and np.isnan(_speed(None))


def test_geojson_and_overpass_readers():
    gj = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[39.1, 21.5], [39.11, 21.5]]},
                "properties": {"fclass": "primary", "oneway": "F", "maxspeed": "60"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "MultiLineString", "coordinates": [[[39.1, 21.5], [39.1, 21.51]], [[39.1, 21.51], [39.11, 21.51]]]},
                "properties": {"highway": "service"},
            },
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [39.1, 21.5]}, "properties": {}},
        ]
    }
    L = from_geojson(gj)
    assert len(L) == 3 and L.fclass == ["primary", "service", "service"] and L.oneway[0] == "F" and L.maxspeed[0] == 60
    ov = {
        "elements": [
            {
                "type": "way",
                "tags": {"highway": "residential", "oneway": "yes"},
                "geometry": [{"lat": 21.5, "lon": 39.1}, {"lat": 21.5, "lon": 39.11}],
            },
            {
                "type": "way",
                "tags": {"highway": "tertiary", "junction": "roundabout"},
                "geometry": [{"lat": 21.5, "lon": 39.1}, {"lat": 21.51, "lon": 39.1}],
            },
            {"type": "way", "tags": {"building": "yes"}, "geometry": [{"lat": 21.5, "lon": 39.1}, {"lat": 21.5, "lon": 39.2}]},
            {"type": "node", "id": 1},
        ]
    }
    L2 = from_overpass(ov)
    assert len(L2) == 2 and L2.oneway == ["F", "F"]  # الدوّار اتجاه واحد افتراضياً
    q = overpass_query((39.1, 21.5, 39.2, 21.6))
    assert "21.5,39.1,21.6,39.2" in q and "out geom" in q


def test_read_roads_bytes_and_errors():
    gj = json.dumps(
        {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[39.1, 21.5], [39.11, 21.5]]},
                    "properties": {"fclass": "primary"},
                }
            ]
        }
    )
    assert len(read_roads(gj.encode(), "x.geojson")) == 1
    with pytest.raises(RoadDataError, match="لا خطوط"):
        read_roads(json.dumps({"features": []}).encode(), "x.geojson")


def test_lines_clip():
    L = lines_xy([[(0, 0), (100, 0)], [(50000, 0), (50100, 0)]])
    lo, la = PROJ.lonlat([X0 - 500, X0 + 500], [Y0 - 500, Y0 + 500])
    c = L.clip((lo[0], la[0], lo[1], la[1]))
    assert len(c) == 1


# ───────── الشبكة والمسافات ─────────
def test_walk_is_manhattan_not_euclid():
    net = RoadNetwork(grid(), PROJ)
    d, i = net.walk_nearest(pt(0, 0), pt(400, 400))
    assert abs(d[0] - 800) < 1 and i[0] == 0  # 4 مربعات شرقاً + 4 شمالاً


def test_walk_within_matches_dijkstra_bruteforce():
    net = RoadNetwork(grid(), PROJ)
    src = np.vstack([pt(x, y) for x in (0, 100, 200, 300, 400) for y in (0, 200, 400)])
    t, s, d = net.walk_within(src, pt(200, 200), 305)
    got = dict(zip(s.tolist(), d.tolist(), strict=True))
    for i, (x, y) in enumerate((x, y) for x in (0, 100, 200, 300, 400) for y in (0, 200, 400)):
        man = abs(x - 200) + abs(y - 200)
        if man <= 300:
            assert abs(got[i] - man) < 1, (x, y)
        else:
            assert i not in got


def test_oneway_drive_asymmetry():
    # حلقة حول مربع باتجاه عقارب الساعة فقط: A(0,0)→B(0,100)→C(100,100)→D(100,0)→A
    ring = [[(0, 0), (0, 100)], [(0, 100), (100, 100)], [(100, 100), (100, 0)], [(100, 0), (0, 0)]]
    net = RoadNetwork(lines_xy(ring, oneway="F"), PROJ)
    ab = net.drive_pairs(pt(0, 0), pt(0, 100))[0]
    ba = net.drive_pairs(pt(0, 100), pt(0, 0))[0]
    assert abs(ab - 100) < 1 and abs(ba - 300) < 1  # العودة تدور حول المربع
    # المشي لا يتأثر بالاتجاه الواحد
    assert abs(net.walk_nearest(pt(0, 100), pt(0, 0))[0][0] - 100) < 1


def test_river_forces_detour_vs_estimate():
    pop = DC.population()
    proj = geo.Projector.for_points(pop.lon, pop.lat)
    net = RoadNetwork(DC.street_lines(), proj)
    ax_, ay_ = proj.xy([39.14], [21.51])  # غرب-جنوب النهر
    bx_, by_ = proj.xy([39.14], [21.57])  # غرب-شمال النهر (الجسر في المنتصف)
    a, b = np.array([[ax_[0], ay_[0]]]), np.array([[bx_[0], by_[0]]])
    est = Access().drive_pairs(a, b)[0]
    osm = Access(net).drive_pairs(a, b)[0]
    assert osm > est * 1.15  # عبور النهر من الجسر الوحيد أطول بوضوح


def test_snap_limit_and_fallback_to_estimate():
    net = RoadNetwork(grid(), PROJ)
    far = pt(2000, 2000)
    assert net.snap(far, "walk")[0][0] == -1
    acc = Access(net)
    d, _ = acc.walk_nearest(far, pt(0, 0))
    assert d[0] == pytest.approx(np.hypot(2000, 2000) * geo.DETOUR, rel=1e-6) and acc.unlinked == 1


def test_largest_component_only():
    segs = [[(i * 100, 0), ((i + 1) * 100, 0)] for i in range(10)] + [[(5000, 5000), (5100, 5000)]]  # جزيرة معزولة
    net = RoadNetwork(lines_xy(segs), PROJ)
    assert len(net._comp["walk"]) == 11 and net.snap(pt(5050, 5000), "walk")[0][0] == -1


def test_network_distance_never_below_straight_line():
    net = RoadNetwork(grid(7), PROJ)
    rng = np.random.default_rng(0)
    xy = np.column_stack([X0 + rng.uniform(0, 600, 15), Y0 + rng.uniform(0, 600, 15)])
    D = Access(net).drive_matrix(xy, xy, "length")
    E = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    assert (D >= E - 1e-6).all()


def test_drive_time_uses_class_and_maxspeed():
    fast = RoadNetwork(lines_xy([[(0, 0), (1000, 0)]], fclass="primary"), PROJ)
    slow = RoadNetwork(lines_xy([[(0, 0), (1000, 0)]], fclass="residential"), PROJ)
    tf = fast.drive_pairs(pt(0, 0), pt(1000, 0), "time")[0]
    ts = slow.drive_pairs(pt(0, 0), pt(1000, 0), "time")[0]
    assert tf < ts
    L = lines_xy([[(0, 0), (1000, 0)]], fclass="residential")
    L.maxspeed = [90.0]
    assert RoadNetwork(L, PROJ).drive_pairs(pt(0, 0), pt(1000, 0), "time")[0] < ts


def test_drive_path_geometry():
    net = RoadNetwork(grid(), PROJ)
    p = net.drive_path(pt(0, 0), pt(200, 100))
    assert p is not None and p[0].tolist() == pytest.approx([X0, Y0], abs=1) and len(p) >= 4
    assert Access().drive_path([0, 0], [10, 10]).shape == (2, 2)  # التقدير: خط مستقيم


# ───────── أثر الشبكة على التحليلات ─────────
def test_coverage_across_river_estimate_vs_osm():
    from transport_hub.transit import coverage as COV

    # شارعان شرق-غرب يفصلهما نهر (بلا وصلة) إلا جسراً بعيداً عند x=2000
    segs = [[(x, 0) for x in range(0, 2001, 100)], [(x, 150) for x in range(0, 2001, 100)], [(2000, 0), (2000, 150)]]
    net = RoadNetwork(lines_xy(segs), PROJ)
    demand = pd.DataFrame({"x": [X0 + 500], "y": [Y0 + 150], "pop": [1000]})
    stop = np.array([[X0 + 500, Y0 + 0]])  # على الضفة الأخرى، 150 م مستقيم
    est = COV.coverage(demand, stop, (400,))
    osm = COV.coverage(demand, stop, (400,), Access(net))
    assert bool(est["covered_400"].iat[0]) and not bool(osm["covered_400"].iat[0])
    assert osm["walk_to_stop_m"].iat[0] > 3000


def test_max_coverage_uses_network_lists():
    from transport_hub.siting import coverage as SC

    segs = [[(x, 0) for x in range(0, 2001, 100)], [(x, 150) for x in range(0, 2001, 100)], [(2000, 0), (2000, 150)]]
    net = RoadNetwork(lines_xy(segs), PROJ)
    dem = np.array([[X0 + 500, Y0 + 150], [X0 + 520, Y0 + 150]])
    cand = np.array([[X0 + 510, Y0 + 0], [X0 + 510, Y0 + 150]])  # الأول عبر النهر
    lists, cov = SC.coverage_inputs(Access(net), dem, cand, 300, existing_xy=None)
    assert cov is None and len(lists[0]) == 0 and len(lists[1]) == 2
    sel, _ = SC.max_coverage(dem, [1, 1], cand, 300, 1, lists=lists)
    assert sel["cand"].iat[0] == 1  # يختار المرشح على نفس الضفة


def test_blocking_deadhead_respects_oneway():
    from transport_hub.ops import blocking as B

    ring = [[(0, 0), (0, 500)], [(0, 500), (500, 500)], [(500, 500), (500, 0)], [(500, 0), (0, 0)]]
    net = RoadNetwork(lines_xy(ring, oneway="F"), PROJ)
    # رحلة تنتهي عند B (0,500) وأخرى تبدأ عند A (0,0): الطريق الفعلي 1500 م (حول الحلقة) لا 500 م
    t = pd.DataFrame(
        [
            dict(trip_id="1", route_id="R", direction_id=0, start=0, end=600, from_x=X0, from_y=Y0, to_x=X0, to_y=Y0 + 500, km=1),
            dict(trip_id="2", route_id="R", direction_id=0, start=1000, end=1600, from_x=X0, from_y=Y0, to_x=X0, to_y=Y0 + 500, km=1),
        ]
    )
    est_ok, _, est_d = B._compat(t, 0, 10_000, 5.0, Access())
    osm_ok, _, osm_d = B._compat(t, 0, 10_000, 5.0, Access(net))
    assert est_d[0, 1] == pytest.approx(500 * geo.DETOUR, rel=1e-6) and osm_d[0, 1] == pytest.approx(1500, abs=2)
    assert osm_d[0, 1] > est_d[0, 1] * 2
    assert est_ok[0, 1] and osm_ok[0, 1]  # كلاهما ممكن لكن بكلفة مختلفة
    _, tight, _ = B._compat(t, 0, 10_000, 1.0, Access(net))
    assert not B._compat(t, 0, 10_000, 1.0, Access(net))[0][0, 1] and B._compat(t, 0, 10_000, 1.0, Access())[0][0, 1] and tight is not None


def test_csa_transfers_blocked_by_river():
    from transport_hub.transit import csa, gtfs

    segs = [[(x, 0) for x in range(0, 2001, 100)], [(x, 150) for x in range(0, 2001, 100)], [(2000, 0), (2000, 150)]]
    net = RoadNetwork(lines_xy(segs), PROJ)
    lo, la = PROJ.lonlat([X0 + 500, X0 + 500, X0 + 1500], [Y0, Y0 + 150, Y0 + 150])
    stops = pd.DataFrame({"stop_id": ["S", "N", "F"], "stop_name": list("SNF"), "stop_lon": lo, "stop_lat": la})
    routes = pd.DataFrame({"route_id": ["X", "Y"]})
    trips = pd.DataFrame({"route_id": ["X", "Y"], "service_id": "WK", "trip_id": ["t1", "t2"], "direction_id": [0, 0]})
    st = pd.DataFrame(
        {
            "trip_id": ["t1", "t1", "t2", "t2"],
            "arrival_time": ["08:00:00", "08:10:00", "08:15:00", "08:30:00"],
            "departure_time": ["08:00:00", "08:10:00", "08:15:00", "08:30:00"],
            "stop_id": ["S", "S", "N", "F"],
            "stop_sequence": [0, 1, 0, 1],
        }
    )
    feed = gtfs.from_tables(dict(stops=stops, routes=routes, trips=trips, stop_times=st))
    o = lambda r: r.earliest_arrival(X0 + 500, Y0, 7.9 * 3600, 400)  # noqa: E731
    est = csa.Router(feed, PROJ)
    osm = csa.Router(feed, PROJ, access=Access(net))
    ids = est.sid
    assert len(est.foot) > 0 and len(osm.foot) == 0  # التبديل بين S وN (150 م مستقيم) مستحيل مشياً عبر النهر
    assert o(est)[ids["F"]] < 1e17 or o(est)[ids["N"]] < 1e17
    assert o(osm)[ids["F"]] > 1e17


def test_load_access_cache_and_toggle(tmp_path):
    w = Workspace(tmp_path)
    assert load_access(w).mode == "estimate"
    w.save_obj("proj_epsg", 32637)
    w.save_obj("roads_lines", grid())
    a = load_access(w)
    assert a.mode == "osm" and "OSM" in a.label()
    assert load_access(w).net is a.net  # الشبكة تُبنى مرة وتُعاد من الكاش
    assert load_access(w, use=False).mode == "estimate"


def test_build_speed_reasonable():
    import time

    big = grid(60, 50.0)  # 120 خطاً × 60 رأساً = 7200 رأس
    t = time.time()
    net = RoadNetwork(big, PROJ)
    assert time.time() - t < 3 and net.n_nodes == 3600


# ───────── تكامل المخرجات والواجهة مع الشبكة ─────────
@pytest.fixture(scope="module")
def city_ws(tmp_path_factory):
    from transport_hub.core import data as D

    w = Workspace(tmp_path_factory.mktemp("cw"))
    d = DC.build_all()
    p = geo.Projector.for_points(d["population"].lon, d["population"].lat)
    w.save_obj("proj_epsg", p.epsg)
    w.save_df("population", D.clean_population(d["population"], p))
    w.save_df("poi", D.clean_poi(d["poi"], p))
    w.save_obj("gtfs", d["gtfs"])
    w.save_df("trips", D.clean_trips(d["trips"], p))
    w.save_df("stands", p.attach(d["stands"]))
    w.save_obj("roads_lines", DC.street_lines())
    return w


def test_package_reflects_distance_mode(city_ws):
    from transport_hub.exports import builder

    m_osm, sheets_osm, _, _ = builder.assemble(city_ws)
    m_est, sheets_est, _, _ = builder.assemble(city_ws, use_roads=False)
    assert "OSM" in m_osm["params"]["طريقة المسافات"] and "تقدير" in m_est["params"]["طريقة المسافات"]
    assert m_osm["fingerprint"] != m_est["fingerprint"]
    assert any("شبكة شوارع OSM" in d for d in m_osm["disclaimers"]) and not any("مستقيمة × 1.3" in d for d in m_osm["disclaimers"])
    assert any("مستقيمة × 1.3" in d for d in m_est["disclaimers"])
    cov = lambda sheets: next(s for s in sheets if s.name == "التغطية حسب الحي").df  # noqa: E731
    assert not np.allclose(cov(sheets_osm)["تغطية_400"].to_numpy(), cov(sheets_est)["تغطية_400"].to_numpy())


def test_network_lowers_coverage_and_lengthens_routes(city_ws):
    from transport_hub.transit import coverage as COV
    from transport_hub.transit import gtfs, planning, service

    feed = gtfs.from_tables(city_ws.obj("gtfs"))
    proj = geo.Projector(city_ws.obj("proj_epsg"))
    pop = city_ws.df("population")
    st = COV.stops_frame(feed, proj)
    sr = service.stop_route_freq(feed)
    est, _ = planning.scenario_kpis(pop, st, sr, access=Access())
    osm, _ = planning.scenario_kpis(pop, st, sr, access=load_access(city_ws))
    assert osm["covered_400_pct"] < est["covered_400_pct"]
    rm_est = service.route_metrics(feed, proj=proj, access=Access())
    rm_osm = service.route_metrics(feed, proj=proj, access=load_access(city_ws))
    assert (rm_osm["length_km"] >= rm_est["length_km"] - 1e-6).all() and rm_osm["length_km"].sum() > rm_est["length_km"].sum()
    assert set(rm_osm["speed_check"]) <= {"معقولة", "مرتفعة: الجدول أسرع من الواقع", "منخفضة: الجدول أبطأ من الطول", "—"}


def test_speed_check_thresholds():
    from transport_hub.transit.service import speed_check

    assert (
        speed_check(20) == "معقولة"
        and speed_check(60).startswith("مرتفعة")
        and speed_check(3).startswith("منخفضة")
        and speed_check(float("nan")) == "—"
    )


def test_blocking_with_network_adds_deadhead(city_ws):
    from transport_hub.ops import blocking as B
    from transport_hub.transit import gtfs

    feed = gtfs.from_tables(city_ws.obj("gtfs"))
    proj = geo.Projector(city_ws.obj("proj_epsg"))
    acc = load_access(city_ws)
    blocks, s = B.build_blocks(B.trip_endpoints(feed, proj, access=acc), access=acc)
    assert blocks["trip_id"].is_unique and s["vehicles"] >= s["theoretical_min"]
    for _, g in blocks.groupby("vehicle"):
        assert (g["start"].to_numpy()[1:] >= g["end"].to_numpy()[:-1]).all()


def test_api_uses_network_and_demo_includes_roads(tmp_path, monkeypatch):
    import json as _json

    from fastapi.testclient import TestClient

    monkeypatch.setenv("TRANSPORT_HUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TRANSPORT_HUB_API_KEYS", _json.dumps({"a": "admin"}))
    import importlib

    import transport_hub.core.store as store

    importlib.reload(store)
    import transport_hub.api as api

    importlib.reload(api)
    c = TestClient(api.app)
    h = {"X-API-Key": "a"}
    c.post("/demo/load", headers=h)
    assert api.ws().has("roads_lines") and api.ws().is_demo()
    routes = c.get("/transit/routes", headers=h).json()
    assert "speed_check" in routes[0] and any(r["length_km"] > 12 for r in routes)  # أطول من تقدير ×1.3 (9.6 كم)


def test_read_shapefile_zip_geofabrik_style(tmp_path):
    gpd = pytest.importorskip("geopandas")
    import shutil

    from shapely.geometry import LineString

    gdf = gpd.GeoDataFrame(
        {"fclass": ["primary", "residential"], "oneway": ["F", "B"], "maxspeed": [60, 0], "name": ["أ", "ب"]},
        geometry=[LineString([(39.10, 21.50), (39.11, 21.50)]), LineString([(39.11, 21.50), (39.11, 21.51)])],
        crs=4326,
    )
    d = tmp_path / "shp"
    d.mkdir()
    gdf.to_file(d / "Roads.shp")
    z = shutil.make_archive(str(tmp_path / "roads"), "zip", d)
    lines = read_roads(open(z, "rb").read(), "roads.zip")
    assert len(lines) == 2 and lines.fclass == ["primary", "residential"] and lines.oneway == ["F", "B"] and lines.maxspeed[0] == 60
    lo, la = PROJ.lonlat([X0], [Y0])
    clipped = read_roads(open(z, "rb").read(), "roads.zip", bbox=(39.095, 21.495, 39.105, 21.505))
    assert len(clipped) >= 1
