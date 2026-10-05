"""أولوية الحافلات (ممر مخصص/أولوية إشارات): ماذا يوفّر تحسين السرعة على الأضلاع الأكثر ازدحاماً في مسار الخط؟
يعيد حساب أزمنة الرحلة بعد الأولوية لكل فترة، ثم أثرها على الأسطول وساعات التشغيل ووقت الركاب."""

import math

import numpy as np
import pandas as pd

from transport_hub.core import congestion as CG
from transport_hub.transit.service import _period_headway_min, trip_table

VALUE_OF_TIME_SAR_H = 20.0


def evaluate(
    feed, proj, access, route_id, lane_share=0.4, delay_cut=0.6, pax_day=None, layover=0.15, days=300, crew_hour=28.0, opex_km=2.2, avg_kmh=18.0
):
    """lane_share: حصة طول المسار (الأعلى تأخيراً) التي تُعطى أولوية. delay_cut: نسبة تقليل التأخير الناتج عن الازدحام على تلك الأضلاع (0.6 = يُزال 60% من زيادة الزمن فوق السير الحر).
    يرجع dict: جدول الفترات (قبل/بعد/وفر/أسطول) وملخص سنوي (ساعات مركبة، تكلفة تشغيل، ساعات ركاب) وأضلاع الأولوية للرسم."""
    t = trip_table(feed)
    g = t[t["route_id"] == route_id]
    if g.empty:
        raise ValueError(f"الخط {route_id} غير موجود")
    st = feed.stop_times.merge(feed.stops[["stop_id", "stop_lat", "stop_lon"]], on="stop_id")
    st["x"], st["y"] = proj.xy(st["stop_lon"], st["stop_lat"])
    dirs = g["direction_id"].nunique()
    reps = []
    for _, gd in g.groupby("direction_id"):
        trip = gd.sort_values("n_stops", ascending=False).iloc[0]["trip_id"]
        reps.append(st[st["trip_id"] == trip].sort_values("stop_sequence"))
    net, prof = access.net, access.profile
    rows, chosen = [], {}
    for period, (lo, hi) in CG.PERIODS.items():
        sub = g[(g["start"] >= lo * 3600) & (g["start"] < hi * 3600)]
        if sub.empty:
            continue
        a = access.with_period(period)
        before, after = [], []
        for s in reps:
            xy = s[["x", "y"]].to_numpy()
            dwell = (s["dep"] - s["arr"]).clip(lower=0).iloc[:-1].sum()
            if net is None:  # بدون شبكة: عامل عام موحّد على كل المسار
                drive = a.drive_pairs(xy[:-1], xy[1:], "time").sum()
                f = a._est_factor()
                after_drive = drive * (lane_share * (1 + (f - 1) * (1 - delay_cut)) / f + (1 - lane_share))
            else:
                ef = prof.edge_factors(period, net) if prof is not None else np.full(net.n_edges, net.default_factor)
                edges = []
                for p0, p1 in zip(xy[:-1], xy[1:], strict=True):
                    e, _ = net.path_edges(p0, p1, prof, period)
                    if e is not None:
                        edges.append(e)
                e_all = np.concatenate(edges) if edges else np.array([], int)
                drive = float((net._dt[e_all] * ef[e_all]).sum())
                delay = net._dt[e_all] * np.maximum(ef[e_all] - 1, 0)
                order = np.argsort(-delay)
                cum = np.cumsum(net._dl[e_all][order])
                pick = order[cum <= lane_share * max(cum[-1], 1)] if len(cum) else order
                ef2 = ef.copy()
                sel = e_all[pick]
                ef2[sel] = 1 + (ef[sel] - 1) * (1 - delay_cut)
                after_drive = float((net._dt[e_all] * ef2[e_all]).sum())
                chosen.setdefault(period, set()).update(sel.tolist())
            before.append((drive + dwell) / 60)
            after.append((after_drive + dwell) / 60)
        tb, ta = float(np.mean(before)), float(np.mean(after))
        hw = np.nanmean([_period_headway_min(gd, lo, hi) for _, gd in g.groupby("direction_id")])
        fb = math.ceil(tb * dirs * (1 + layover) / hw) if hw == hw and hw else np.nan
        fa = math.ceil(ta * dirs * (1 + layover) / hw) if hw == hw and hw else np.nan
        rows.append(
            dict(
                period=period,
                trips=len(sub),
                before_min=round(tb, 1),
                after_min=round(ta, 1),
                saved_min=round(tb - ta, 1),
                saved_pct=round(100 * (tb - ta) / tb, 1) if tb else 0.0,
                fleet_before=fb,
                fleet_after=fa,
            )
        )
    tab = pd.DataFrame(rows)
    veh_h = float((tab["saved_min"] * tab["trips"]).sum() / 60 * days)
    km_per_h = avg_kmh
    summary = dict(
        vehicle_hours_saved_year=veh_h,
        opex_saving_year=veh_h * (crew_hour + opex_km * km_per_h),
        fleet_saved=int(np.nanmax(tab["fleet_before"]) - np.nanmax(tab["fleet_after"])) if len(tab) else 0,
    )
    if pax_day:
        avg_save = float(np.average(tab["saved_min"], weights=tab["trips"])) / 2  # الراكب في المتوسط يقضي نصف الرحلة
        summary["passenger_hours_saved_year"] = pax_day * avg_save / 60 * days
        summary["passenger_value_year"] = summary["passenger_hours_saved_year"] * VALUE_OF_TIME_SAR_H
    links = None
    if net is not None and chosen:
        idx = np.array(sorted(set().union(*chosen.values())), int)
        xy = net.node_xy
        links = pd.DataFrame(
            {"xa": xy[net._du[idx], 0], "ya": xy[net._du[idx], 1], "xb": xy[net._dv[idx], 0], "yb": xy[net._dv[idx], 1], "length_m": net._dl[idx]}
        )
    return dict(table=tab, summary=summary, links=links)
