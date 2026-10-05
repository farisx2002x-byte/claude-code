"""تغطية خدمة النقل العام وسهولة الوصول: نسبة التغطية، مؤشر مستوى الخدمة (على طريقة PTAL)، والفجوات."""

import numpy as np
import pandas as pd

from transport_hub.core import geo
from transport_hub.core.access import Access

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


def coverage(demand, stops_xy, radii=(400, 800), access=None):
    """لكل منطقة طلب: مسافة المشي لأقرب محطة (على شبكة الشوارع إن توفرت، وإلا مستقيم × معامل التعرج)، وهل هي مغطاة عند كل نصف قطر."""
    access = access or Access()
    d, _ = access.walk_nearest(demand[["x", "y"]].to_numpy(), np.asarray(stops_xy, float), limit=max(max(radii) * 3, 3000))
    out = demand.copy()
    out["walk_to_stop_m"] = d
    for r in radii:
        out[f"covered_{r}"] = out["walk_to_stop_m"] <= r
    return out


def accessibility_index(demand, stops, stop_route, walk_max=WALK_MAX_M, access=None):
    """مؤشر مستوى الخدمة لكل منطقة: لكل خط نأخذ أفضل محطة (مشي + نصف التردد + زمن إضافي)، EDF = 30/زمن،
    المؤشر = أعلى EDF + 0.5 × مجموع الباقي. stop_route: stop_id, route_id, headway_min. مسافات المشي من access."""
    access = access or Access()
    t, s, dist = access.cover(demand[["x", "y"]].to_numpy(), stops[["x", "y"]].to_numpy(), walk_max)
    sr = stop_route.groupby("stop_id")[["route_id", "headway_min"]].apply(lambda g: list(zip(g["route_id"], g["headway_min"], strict=True))).to_dict()
    sid = stops["stop_id"].to_numpy()
    per_demand = {}
    for ti, si, di in zip(t, s, dist, strict=True):
        per_demand.setdefault(si, []).append((sid[ti], di))
    ai = np.zeros(len(demand))
    for i, nb in per_demand.items():
        best = {}
        for stop_id, d in nb:
            walk = d / (geo.WALK_KMH * 1000 / 60)
            for rid, hw in sr.get(stop_id, ()):
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
