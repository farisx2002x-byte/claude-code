import itertools

import numpy as np
import pandas as pd
import pytest

from transport_hub.admin import equity, finance, scorecard
from transport_hub.core import demand as DM
from transport_hub.core import demo_city as DC
from transport_hub.core import geo
from transport_hub.siting import coverage as SC
from transport_hub.siting import mcda
from transport_hub.taxi import demand as TD
from transport_hub.taxi import fleet as TF
from transport_hub.taxi import supply as TS
from transport_hub.transit import coverage as COV
from transport_hub.transit import csa, gtfs, planning, service, timetable


# ───────── مدينة صغيرة لكل الاختبارات ─────────
@pytest.fixture(scope="module")
def city():
    d = DC.build_all()
    proj = geo.Projector.for_points(d["population"].lon, d["population"].lat)
    from transport_hub.core import data as D

    pop = D.clean_population(d["population"], proj)
    feed = gtfs.from_tables(d["gtfs"])
    return dict(pop=pop, poi=D.clean_poi(d["poi"], proj), feed=feed, proj=proj, trips=D.clean_trips(d["trips"], proj), raw=d)


def test_projector_roundtrip():
    p = geo.Projector.for_points([39.17], [21.54])
    assert p.epsg == 32637
    x, y = p.xy([39.17], [21.54])
    lo, la = p.lonlat(x, y)
    assert abs(lo[0] - 39.17) < 1e-6 and abs(la[0] - 21.54) < 1e-6


def test_gtfs_validate_detects_problems(city):
    f = city["feed"]
    assert gtfs.validate(f)["العدد"].sum() == 0
    bad = gtfs.Feed(f.stops, f.routes, f.trips, f.stop_times.assign(stop_id="NOPE"), f.calendar)
    assert gtfs.validate(bad).set_index("الفحص").loc["stop_times تشير لمحطة غير موجودة", "العدد"] > 0
    with pytest.raises(ValueError):
        gtfs.from_tables({"stops": f.stops})


def test_gtfs_time_over_24h():
    assert gtfs.parse_time(pd.Series(["25:30:00"])).iat[0] == 25 * 3600 + 1800


def test_headway_and_fleet(city):
    rm = service.route_metrics(city["feed"], proj=city["proj"])
    r1 = rm.set_index("route_id").loc["R1"]
    assert r1["peak_headway_min"] == 10
    assert r1["peak_fleet"] >= int(r1["run_time_min"] * 2 / 10)  # على الأقل زمن الدورة ÷ التردد


def test_coverage_monotonic_in_radius(city):
    st = COV.stops_frame(city["feed"], city["proj"])
    c = COV.coverage(city["pop"], st[["x", "y"]].to_numpy(), (300, 600, 900))
    assert c["covered_300"].sum() <= c["covered_600"].sum() <= c["covered_900"].sum()


def test_accessibility_index_improves_with_frequency(city):
    st = COV.stops_frame(city["feed"], city["proj"])
    sr = service.stop_route_freq(city["feed"])
    k0, _ = planning.scenario_kpis(city["pop"], st, sr)
    k1, _ = planning.scenario_kpis(city["pop"], st, sr, headway_factor={r: 0.5 for r in sr["route_id"].unique()})
    assert k1["avg_access_index"] > k0["avg_access_index"]
    assert k1["covered_400_pct"] == k0["covered_400_pct"]  # التردد لا يغير التغطية المكانية


def test_new_stops_increase_coverage(city):
    st = COV.stops_frame(city["feed"], city["proj"])
    cand = geo.candidate_grid(city["pop"]["x"], city["pop"]["y"], 250)
    sel, (b, a) = planning.suggest_stops(city["pop"], st[["x", "y"]].to_numpy(), cand, 400, 6)
    assert a > b and (sel["gain"] > 0).all() and sel["gain"].is_monotonic_decreasing


# ───────── CSA على شبكة صغيرة بنتيجة معروفة ─────────
def tiny_feed():
    stops = pd.DataFrame({"stop_id": ["A", "B", "C"], "stop_name": list("ABC"), "stop_lat": [21.5, 21.5, 21.5], "stop_lon": [39.10, 39.15, 39.20]})
    routes = pd.DataFrame({"route_id": ["X", "Y"]})
    trips = pd.DataFrame({"route_id": ["X", "Y"], "service_id": ["WK"] * 2, "trip_id": ["t1", "t2"], "direction_id": [0, 0]})
    st = pd.DataFrame(
        {
            "trip_id": ["t1", "t1", "t2", "t2"],
            "arrival_time": ["08:00:00", "08:10:00", "08:20:00", "08:30:00"],
            "departure_time": ["08:00:00", "08:10:00", "08:20:00", "08:30:00"],
            "stop_id": ["A", "B", "B", "C"],
            "stop_sequence": [0, 1, 0, 1],
        }
    )
    return gtfs.from_tables(dict(stops=stops, routes=routes, trips=trips, stop_times=st))


def test_csa_transfer_and_miss():
    f = tiny_feed()
    proj = geo.Projector.for_points(f.stops.stop_lon, f.stops.stop_lat)
    r = csa.Router(f, proj)
    a = f.stops[f.stops.stop_id == "A"]
    x, y = proj.xy(a.stop_lon, a.stop_lat)
    arr = r.earliest_arrival(x[0], y[0], 7.95 * 3600)
    ids = {s: arr[i] for s, i in r.sid.items()}
    assert ids["B"] == 8 * 3600 + 600 and ids["C"] == 8 * 3600 + 1800  # تبديل في B على الرحلة الثانية
    late = r.earliest_arrival(x[0], y[0], 8.2 * 3600)  # فاتت الرحلة الأولى
    assert late[r.sid["C"]] > 1e17


# ───────── اختيار المواقع ─────────
def test_greedy_vs_exact_and_bounds():
    rng = np.random.default_rng(0)
    dem = rng.uniform(0, 3000, (200, 2))
    w = rng.integers(1, 20, 200).astype(float)
    cand = rng.uniform(0, 3000, (80, 2))
    g, (b, a) = SC.max_coverage(dem, w, cand, 500, 5)
    ex = SC.max_coverage_exact(dem, w, cand, 500, 5, time_s=10)
    cov_ex = np.zeros(200, bool)
    for lst in __import__("scipy.spatial", fromlist=["cKDTree"]).cKDTree(dem).query_ball_point(cand[ex], 500):
        cov_ex[lst] = True
    opt = 100 * w[cov_ex].sum() / w.sum()
    assert a <= opt + 1e-6 and a >= 0.63 * opt  # ضمان التقريب الجشع
    assert g["cum_covered_pct"].is_monotonic_increasing


def test_p_median_matches_brute_force_small():
    rng = np.random.default_rng(1)
    dem = rng.uniform(0, 1000, (30, 2))
    w = rng.integers(1, 10, 30).astype(float)
    cand = rng.uniform(0, 1000, (10, 2))
    _, _, cost = SC.p_median(dem, w, cand, 2)
    from scipy.spatial.distance import cdist

    D = cdist(dem, cand)
    best = min((w * D[:, list(c)].min(axis=1)).sum() for c in itertools.combinations(range(10), 2))
    assert cost <= best * 1.05


def test_mcda_normalization_and_spacing():
    cand = pd.DataFrame({"x": np.arange(10) * 100.0, "y": 0.0})
    crit = [mcda.Criterion("a", np.arange(10.0), 1.0, True), mcda.Criterion("b", np.arange(10.0), 1.0, False)]
    s = mcda.score(cand, crit)
    assert np.allclose(s["score"], 50)  # معياران متعاكسان بنفس الوزن
    crit2 = [mcda.Criterion("a", np.arange(10.0), 1.0, True)]
    top = mcda.pick(mcda.score(cand, crit2), 3, 250)
    assert len(top) == 3 and top["x"].diff().abs().dropna().min() >= 250


# ───────── التاكسي ─────────
def test_erlang_c_known_values():
    assert abs(TF.erlang_c(1, 0.5) - 0.5) < 1e-9  # M/M/1: احتمال الانتظار = ρ
    assert TF.erlang_c(2, 2.5) == 1.0
    assert TF.avg_wait_min(14, 60, 10) < TF.avg_wait_min(11, 60, 10) < float("inf")  # مركبات أكثر → انتظار أقل
    n = TF.vehicles_for_wait(60, 20, 3)
    assert TF.avg_wait_min(n, 60, 20) <= 3 and TF.avg_wait_min(n - 1, 60, 20) > 3


def test_rebalance_conserves_vehicles():
    bal = pd.DataFrame({"name": list("ABCD"), "x": [0, 1000, 2000, 3000.0], "y": 0.0, "balance": [5.0, -3.0, -2.0, 0.0]})
    plan = TS.rebalance_plan(bal)
    assert plan["vehicles"].sum() == 5
    assert set(plan["from"]) == {"A"} and set(plan["to"]) == {"B", "C"}


def test_hotspots_cover_requested_share(city):
    hs = TD.hotspots(city["trips"], 400, 0.5)
    assert 45 <= hs["share_pct"].sum() <= 75
    assert hs["trips_per_day"].is_monotonic_decreasing


# ───────── الإدارة والتمويل والطلب ─────────
def test_gini_extremes():
    assert abs(equity.gini([5, 5, 5, 5], [1, 1, 1, 1])) < 1e-9
    assert equity.gini([0, 0, 0, 10], [1, 1, 1, 1]) > 0.7


def test_scorecard_status():
    assert scorecard.status(70, 60, "up") == "🟢" and scorecard.status(55, 60, "up") == "🟡" and scorecard.status(20, 60, "up") == "🔴"
    assert scorecard.status(4, 5, "down") == "🟢" and scorecard.status(9, 5, "down") == "🔴"


def test_knapsack_optimal():
    p = pd.DataFrame({"name": list("ABCD"), "cost": [10, 20, 30, 40], "benefit": [10, 30, 36, 40]})
    ch, _ = finance.prioritize(p, 50)
    assert set(ch["name"]) == {"B", "C"}  # 66 أفضل من A+D=50 أو A+B+... ضمن 50


def test_annual_cost_components():
    c = finance.annual_cost("باص كبير", 10, 2000, 100)
    assert abs(c["total"] - (c["capital"] + c["operating"] + c["crew"])) < 1e-6 and c["co2_t"] > 0


def test_gravity_conserves_trips(city):
    z, od, T = DM.gravity(city["pop"], city["poi"], 0.25, 2.0)
    assert abs(T.sum() - city["pop"]["pop"].sum() * 2.0) < 1e-3
    z2, _, _ = DM.gravity(city["pop"], city["poi"], 1.0, 2.0)
    assert z2["avg_trip_km"].mean() < z["avg_trip_km"].mean()  # β أكبر → رحلات أقصر


def test_timetable_generates_valid_feed(city):
    tb = timetable.build_line("N1", "جديد", [("a", 39.1, 21.5), ("b", 39.12, 21.5), ("c", 39.14, 21.51)])
    f = gtfs.from_tables(timetable.merge_tables(city["raw"]["gtfs"], tb))
    assert gtfs.validate(f)["العدد"].sum() == 0 and "N1" in set(f.routes.route_id)
