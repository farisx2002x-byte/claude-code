"""مستوى الخدمة: الترددات، مقاييس الخطوط، الأسطول المطلوب، ومحاور التبديل."""

import math

import numpy as np
import pandas as pd

from transport_hub.core import geo

PERIODS = {"الذروة الصباحية": (6, 9), "منتصف النهار": (9, 15), "الذروة المسائية": (15, 19), "المساء": (19, 24)}


def trip_table(feed, weekday=None):
    """جدول لكل رحلة: الخط، الاتجاه، أول انطلاق، آخر وصول، عدد المحطات، المدة."""
    from transport_hub.transit.gtfs import active_trips

    st = feed.stop_times
    g = st.groupby("trip_id").agg(start=("dep", "min"), end=("arr", "max"), n_stops=("stop_id", "size"))
    t = active_trips(feed, weekday).merge(g, left_on="trip_id", right_index=True)
    t["duration_min"] = (t["end"] - t["start"]) / 60.0
    t["hour"] = (t["start"] // 3600).astype(int)
    t["direction_id"] = t["direction_id"].astype(str)
    return t


def headways(feed, weekday=None):
    """متوسط التردد (دقيقة) لكل خط واتجاه وفترة (من فروقات الانطلاق الفعلية)."""
    t = trip_table(feed, weekday)
    rows = []
    for (rid, d), g in t.groupby(["route_id", "direction_id"]):
        for name, (h0, h1) in PERIODS.items():
            s = np.sort(g.loc[(g["start"] >= h0 * 3600) & (g["start"] < h1 * 3600), "start"].values)
            hw = float(np.diff(s).mean() / 60) if len(s) > 1 else np.nan
            rows.append(dict(route_id=rid, direction=d, period=name, trips=len(s), headway_min=hw))
    return pd.DataFrame(rows)


def route_metrics(feed, weekday=None, proj=None, layover=0.15):
    """مقاييس كل خط: الطول، المحطات، تباعد المحطات، السرعة التجارية، الرحلات اليومية، والأسطول المطلوب للذروة."""
    t = trip_table(feed, weekday)
    st = feed.stop_times.merge(feed.stops[["stop_id", "stop_lat", "stop_lon"]], on="stop_id")
    proj = proj or geo.Projector.for_points(feed.stops["stop_lon"].dropna(), feed.stops["stop_lat"].dropna())
    st["x"], st["y"] = proj.xy(st["stop_lon"], st["stop_lat"])
    hw = headways(feed, weekday)
    rows = []
    names = feed.routes.set_index("route_id")["route_long_name"].to_dict()
    for rid, g in t.groupby("route_id"):
        # رحلة تمثيلية: الأكثر محطات
        rep = g.sort_values("n_stops", ascending=False).iloc[0]
        s = st[st["trip_id"] == rep["trip_id"]].sort_values("stop_sequence")
        seg = np.hypot(np.diff(s["x"].values), np.diff(s["y"].values)) * geo.DETOUR
        length_km = float(seg.sum() / 1000)
        dur = float(rep["duration_min"])
        peak_hw = hw[(hw.route_id == rid) & (hw.period.isin(["الذروة الصباحية", "الذروة المسائية"]))]["headway_min"].min()
        # الأسطول: زمن الدورة (ذهاب+إياب مع استراحة) ÷ التردد
        dirs = g["direction_id"].nunique()
        cycle = dur * dirs * (1 + layover) if dirs else dur
        fleet = math.ceil(cycle / peak_hw) if peak_hw and not np.isnan(peak_hw) else np.nan
        rows.append(
            dict(
                route_id=rid,
                name=names.get(rid, rid),
                stops=int(rep["n_stops"]),
                length_km=round(length_km, 1),
                avg_stop_spacing_m=round(seg.mean(), 0) if len(seg) else np.nan,
                run_time_min=round(dur, 1),
                commercial_speed_kmh=round(length_km / (dur / 60), 1) if dur else np.nan,
                trips_per_day=len(g),
                peak_headway_min=round(peak_hw, 1) if peak_hw == peak_hw else np.nan,
                peak_fleet=fleet,
                service_span=f"{int(g['start'].min() // 3600):02d}:00–{int(g['end'].max() // 3600):02d}:00",
            )
        )
    return pd.DataFrame(rows)


def stop_departures(feed, weekday=None, hours=(7, 9)):
    """عدد المغادرات في الساعة لكل محطة خلال الفترة (للتغطية الموزونة بالتردد)."""
    t = trip_table(feed, weekday)[["trip_id", "route_id"]]
    st = feed.stop_times.merge(t, on="trip_id")
    h = st["dep"] // 3600
    st = st[(h >= hours[0]) & (h < hours[1])]
    span = max(hours[1] - hours[0], 1)
    g = st.groupby("stop_id").agg(deps_per_hour=("trip_id", lambda s: len(s) / span), routes=("route_id", "nunique"))
    return g


def hubs(feed, proj, radius=200):
    """محاور التبديل: محطات (أو مجموعات محطات ضمن radius م) يمر بها أكثر من خط."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    t = trip_table(feed)[["trip_id", "route_id"]]
    st = feed.stop_times.merge(t, on="trip_id")[["stop_id", "route_id"]].drop_duplicates()
    stops = feed.stops[feed.stops["stop_id"].isin(st["stop_id"])].reset_index(drop=True)
    stops["x"], stops["y"] = proj.xy(stops["stop_lon"], stops["stop_lat"])
    xy = stops[["x", "y"]].to_numpy()
    pairs = np.array(sorted(cKDTree(xy).query_pairs(radius)))
    n = len(stops)
    if len(pairs):
        lab = connected_components(coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n)), directed=False)[1]
    else:
        lab = np.arange(n)
    stops["cluster"] = lab
    m = st.merge(stops[["stop_id", "cluster"]], on="stop_id")
    g = m.groupby("cluster")["route_id"].nunique()
    out = stops.groupby("cluster").agg(x=("x", "mean"), y=("y", "mean"), stops=("stop_id", "size")).join(g.rename("routes"))
    out = out[out["routes"] > 1].sort_values("routes", ascending=False).reset_index()
    out["lon"], out["lat"] = proj.lonlat(out["x"], out["y"])
    return out


def stop_route_freq(feed, weekday=None, hours=(7, 9)):
    """مغادرات الساعة لكل (محطة، خط) في فترة الذروة، مع التردد المكافئ بالدقائق."""
    t = trip_table(feed, weekday)[["trip_id", "route_id"]]
    st = feed.stop_times.merge(t, on="trip_id")
    h = st["dep"] // 3600
    st = st[(h >= hours[0]) & (h < hours[1])]
    g = st.groupby(["stop_id", "route_id"]).size().rename("deps").reset_index()
    g["deps_per_hour"] = g["deps"] / max(hours[1] - hours[0], 1)
    g["headway_min"] = 60.0 / g["deps_per_hour"]
    return g
