"""مولّد جداول الرحلات: من تعريف خط (محطات + ترددات حسب الفترة) إلى GTFS جاهز للتبديل مع المشغّلين."""
import numpy as np
import pandas as pd

from transport_hub.core import geo

DEFAULT_PERIODS = [(6, 9, 10), (9, 15, 20), (15, 19, 10), (19, 22, 30)]     # (من ساعة, إلى ساعة, تردد د)


def _t(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def build_line(route_id, name, stops, periods=None, speed_kmh=20, dwell_s=30, service_id="WK", both_directions=True):
    """stops: قائمة (اسم, lon, lat). يرجع dict جداول GTFS (stops, routes, trips, stop_times)."""
    periods = periods or DEFAULT_PERIODS
    sid = [f"{route_id}_S{k + 1}" for k in range(len(stops))]
    stops_df = pd.DataFrame({"stop_id": sid, "stop_name": [s[0] for s in stops], "stop_lon": [s[1] for s in stops], "stop_lat": [s[2] for s in stops]})
    d = [0.0] + [float(geo.haversine_m(stops[i][1], stops[i][2], stops[i + 1][1], stops[i + 1][2])) * geo.DETOUR for i in range(len(stops) - 1)]
    trips, st = [], []
    for direction in ((0, 1) if both_directions else (0,)):
        seq = list(range(len(stops))) if direction == 0 else list(range(len(stops)))[::-1]
        legs = d if direction == 0 else [0.0] + d[1:][::-1]
        for h0, h1, hw in periods:
            t = h0 * 3600
            while t < h1 * 3600:
                tid = f"{route_id}_{direction}_{int(t)}"
                trips.append(dict(route_id=route_id, service_id=service_id, trip_id=tid, direction_id=direction))
                cur = t
                for n, k in enumerate(seq):
                    if n:
                        cur += legs[n] / (speed_kmh / 3.6)
                    st.append(dict(trip_id=tid, arrival_time=_t(cur), departure_time=_t(cur + dwell_s), stop_id=sid[k], stop_sequence=n))
                    cur += dwell_s
                t += hw * 60
    return dict(stops=stops_df, routes=pd.DataFrame([dict(route_id=route_id, route_short_name=route_id, route_long_name=name, route_type=3)]),
                trips=pd.DataFrame(trips), stop_times=pd.DataFrame(st))


def merge_tables(base, extra):
    out = {}
    for k in ("stops", "routes", "trips", "stop_times"):
        out[k] = pd.concat([base[k], extra[k]], ignore_index=True)
    out["calendar"] = base.get("calendar", pd.DataFrame())
    if len(out["calendar"]) == 0:
        out["calendar"] = pd.DataFrame([dict(service_id="WK", monday=1, tuesday=1, wednesday=1, thursday=1, friday=0, saturday=0, sunday=1,
                                             start_date="20250101", end_date="20251231")])
    return out
