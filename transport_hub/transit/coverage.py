"""تغطية خدمة النقل العام وسهولة الوصول: نسبة التغطية، مؤشر مستوى الخدمة (على طريقة PTAL)، والفجوات."""

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from transport_hub.core import geo

GRADES = [(2.5, "1 — ضعيف جداً"), (5, "2 — ضعيف"), (10, "3 — متوسط"), (15, "4 — جيد"), (20, "5 — جيد جداً"), (1e9, "6 — ممتاز")]
SWT_EXTRA_MIN = 2.0  # زمن إضافي لعدم الانتظام (تقديري)
WALK_MAX_M = 640  # ≈ 8 دقائق مشي (حد PTAL للحافلات)


def grade_of(ai):
    for lim, name in GRADES:
        if ai <= lim:
            return name
    return GRADES[-1][1]


def stops_frame(feed, proj):
    s = feed.stops.dropna(subset=["stop_lat", "stop_lon"]).copy()
    s["x"], s["y"] = proj.xy(s["stop_lon"], s["stop_lat"])
    return s


def coverage(demand, stops_xy, radii=(400, 800)):
    """لكل منطقة طلب: المسافة (الفعلية بعد التعرج) لأقرب محطة، وهل هي مغطاة عند كل نصف قطر."""
    d, _ = geo.nearest(demand[["x", "y"]].to_numpy(), stops_xy)
    out = demand.copy()
    out["walk_to_stop_m"] = d * geo.DETOUR
    for r in radii:
        out[f"covered_{r}"] = out["walk_to_stop_m"] <= r
    return out


def accessibility_index(demand, stops, stop_route, walk_max=WALK_MAX_M):
    """مؤشر مستوى الخدمة لكل منطقة: لكل خط نأخذ أفضل محطة (مشي + نصف التردد + زمن إضافي)، EDF = 30/زمن،
    المؤشر = أعلى EDF + 0.5 × مجموع الباقي. stop_route: stop_id, route_id, headway_min."""
    tree = cKDTree(stops[["x", "y"]].to_numpy())
    near = tree.query_ball_point(demand[["x", "y"]].to_numpy(), walk_max / geo.DETOUR)
    sr = stop_route.set_index("stop_id")
    sidx = stops["stop_id"].values
    ai = np.zeros(len(demand))
    dx, dy = demand["x"].to_numpy(), demand["y"].to_numpy()
    sx, sy = stops["x"].to_numpy(), stops["y"].to_numpy()
    for i, nb in enumerate(near):
        if not nb:
            continue
        best = {}
        for j in nb:
            sid = sidx[j]
            if sid not in sr.index:
                continue
            walk = geo.walk_minutes(np.hypot(sx[j] - dx[i], sy[j] - dy[i]))
            rows = sr.loc[[sid]]
            for rid, hw in zip(rows["route_id"], rows["headway_min"]):
                wt = walk + 0.5 * hw + SWT_EXTRA_MIN
                if rid not in best or wt < best[rid]:
                    best[rid] = wt
        if best:
            edf = sorted((30.0 / w for w in best.values()), reverse=True)
            ai[i] = edf[0] + 0.5 * sum(edf[1:])
    out = demand.copy()
    out["access_index"] = ai
    out["grade"] = [grade_of(a) if a > 0 else "0 — بلا خدمة" for a in ai]
    return out


def summary(cov, by="district"):
    """ملخص التغطية: إجمالي ولكل حي (موزون بالسكان)."""
    rows = {"الإجمالي": cov}
    if by in cov:
        rows.update({k: g for k, g in cov.groupby(by)})
    out = []
    for name, g in rows.items():
        p = g["pop"].sum()
        row = dict(المنطقة=name, السكان=int(p))
        for c in [c for c in g.columns if c.startswith("covered_")]:
            row[f"تغطية {c.split('_')[1]} م %"] = round(100 * g.loc[g[c], "pop"].sum() / p, 1) if p else 0
        if "access_index" in g:
            row["متوسط مؤشر الخدمة"] = round(np.average(g["access_index"], weights=g["pop"]) if p else 0, 1)
        out.append(row)
    return pd.DataFrame(out)
