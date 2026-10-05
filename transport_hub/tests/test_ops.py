import numpy as np
import pandas as pd
import pytest

from transport_hub.core import demo_city as DC
from transport_hub.core import geo
from transport_hub.ops import blocking as B
from transport_hub.ops import fleetmgmt as F
from transport_hub.ops import performance as P
from transport_hub.transit import gtfs


def trip(tid, s, e, a_to_b=True, route="R"):
    ax, bx = (0.0, 5000.0) if a_to_b else (5000.0, 0.0)
    return dict(trip_id=tid, route_id=route, direction_id=0 if a_to_b else 1, start=s * 60, end=e * 60, from_x=ax, from_y=0.0, to_x=bx, to_y=0.0, km=6.0)


def test_blocking_hand_example():
    t = pd.DataFrame([trip("T1", 480, 510), trip("T2", 515, 540, False), trip("T3", 490, 520), trip("T4", 525, 550, False)])
    blocks, s = B.build_blocks(t, layover_min=5, minimize_cost=True)
    assert s["vehicles"] == 2 and s["theoretical_min"] == 2
    assert blocks.groupby("vehicle")["trip_id"].apply(list).map(len).tolist() == [2, 2]
    # بدون وقت استراحة كافٍ لا يمكن ربطهما
    t2 = pd.DataFrame([trip("A", 480, 510), trip("B", 512, 540, False)])
    assert B.build_blocks(t2, layover_min=5)[1]["vehicles"] == 2
    assert B.build_blocks(t2, layover_min=1)[1]["vehicles"] == 1


def test_blocking_cardinality_matches_min_cost_fleet():
    d = DC.gtfs_feed()
    f = gtfs.from_tables(d)
    proj = geo.Projector.for_points(f.stops.stop_lon, f.stops.stop_lat)
    t = B.trip_endpoints(f, proj)
    a = B.build_blocks(t, minimize_cost=True)[1]
    b = B.build_blocks(t, minimize_cost=False)[1]
    assert a["vehicles"] == b["vehicles"] >= a["theoretical_min"]       # نفس الحجم الأدنى بالطريقتين
    blocks = B.build_blocks(t)[0]
    assert blocks["trip_id"].is_unique and len(blocks) == len(t)        # كل رحلة في مركبة واحدة بالضبط
    # لا تداخل داخل نفس المركبة
    for _, g in blocks.groupby("vehicle"):
        assert (g["start"].to_numpy()[1:] >= g["end"].to_numpy()[:-1]).all()


def test_duties_respect_limits():
    rows = [trip(f"T{i}", 360 + i * 80, 420 + i * 80) for i in range(6)]       # ساعة تشغيل ثم 20 د استراحة
    blocks = pd.DataFrame(rows).assign(vehicle=0)
    d, s = B.duties(blocks, max_drive_h=4.5, min_break_min=15, max_duty_h=12)
    assert s["violations"] == 0 and s["pieces"] == 2 and d["drive_h"].max() <= 4.5
    d2, s2 = B.duties(blocks, max_drive_h=4.5, min_break_min=30, max_duty_h=12)   # لا فرصة تبديل (20 د < 30)
    assert s2["violations"] >= 1


def avl(rows):
    return P.clean_avl(pd.DataFrame(rows, columns=["date", "route_id", "trip_id", "stop_id", "scheduled", "actual"]))


def test_on_time_known():
    a = avl([("d", "R", f"t{i}", "S", 1000, 1000 + dly) for i, dly in enumerate([0, 400, -100])])
    o = P.on_time(a).iloc[0]
    assert abs(o["on_time_pct"] - 33.3) < 0.1 and abs(o["late_pct"] - 33.3) < 0.1 and abs(o["early_pct"] - 33.3) < 0.1


def test_ewt_known_value():
    a = avl([("d", "R", f"t{i}", "S", s * 60, act * 60) for i, (s, act) in enumerate([(0, 0), (10, 5), (20, 20)])])
    _, br = P.headway_regularity(a, {"R": 10})
    assert abs(br["ewt_min"].iat[0] - 1.25) < 1e-9
    reg = avl([("d", "R", f"t{i}", "S", i * 600, i * 600) for i in range(5)])
    assert abs(P.headway_regularity(reg)[1]["ewt_min"].iat[0]) < 1e-9       # انتظام تام: EWT = 0


def test_apc_load():
    apc = P.clean_apc(pd.DataFrame({"date": "d", "route_id": "R", "trip_id": "t", "stop_id": list("abc"), "boardings": [10, 5, 0], "alightings": [0, 3, 12]}))
    s = P.apc_summary(apc, 12).iloc[0]
    assert s["avg_max_load"] == 12 and s["crowded_trips_pct"] == 100       # 12 > 0.9×12


def test_missing_columns_message():
    with pytest.raises(ValueError, match="أعمدة ناقصة"):
        P.clean_avl(pd.DataFrame({"date": [1]}))
    with pytest.raises(ValueError, match="أعمدة ناقصة"):
        F.clean_register(pd.DataFrame({"vehicle_id": [1]}))


def test_maintenance_status():
    reg = F.clean_register(pd.DataFrame({"vehicle_id": [1, 2, 3], "type": "x", "seats": 72, "year": 2020, "odometer_km": [100_000, 100_000, 100_000],
                                         "last_service_km": [85_000, 91_000, 98_000], "last_service_date": ["2025-02-20"] * 3}))
    m = F.maintenance(reg, 100, today="2025-03-02").set_index("vehicle_id")
    assert m.loc[1, "status"] == "متأخرة" and m.loc[2, "status"] == "قريبة" and m.loc[3, "status"] == "سليمة"


def test_ev_feasibility_and_tco():
    blocks = pd.DataFrame({"vehicle": [0, 1], "km": [100.0, 200.0]})
    v, s = F.ev_feasibility(blocks, kwh_per_km=1.6, battery_kwh=350, usable=0.8, reserve=0.1)
    assert v["feasible"].tolist() == [True, False] and s["feasible_pct"] == 50.0
    assert v["needs_midday_charge_kwh"].iat[1] == pytest.approx(320 - 245)
    cheap = F.tco(80_000, 12, ev=dict(price=700_000, kwh_km=1.2, kwh_price=0.1, maint_km=0.3, charger=50_000))
    assert cheap["saving"] > 0 and cheap["payback_years"] < 12
    dear = F.tco(20_000, 12)
    assert dear["saving"] < 0
