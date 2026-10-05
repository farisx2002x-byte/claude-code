"""طلب التاكسي: نمط الساعات، النقاط الساخنة، ومصفوفة الأصل-الوجهة."""

import numpy as np
import pandas as pd
from scipy.ndimage import label

from transport_hub.core import geo


def n_days(trips):
    return max(trips["date"].nunique(), 1)


def hourly_profile(trips):
    """متوسط الرحلات لكل ساعة في اليوم (وفق عدد الأيام الفعلية)، وحسب نوع اليوم."""
    d = n_days(trips)
    h = trips.groupby("hour").size().reindex(range(24), fill_value=0) / d
    return pd.DataFrame({"hour": range(24), "trips_per_day": h.values})


def dow_profile(trips):
    names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    g = trips.groupby(["dow", "date"]).size().groupby("dow").mean().reindex(range(7), fill_value=0)
    return pd.DataFrame({"day": names, "trips_per_day": g.values})


def grid_demand(trips, cell=500, hours=None):
    """عدد الرحلات (يومياً) لكل خلية، مع فلتر ساعات اختياري (hours = مجموعة ساعات)."""
    t = trips if hours is None else trips[trips["hour"].isin(hours)]
    ix, iy, cx, cy = geo.grid_cells(t["px"], t["py"], cell)
    g = pd.DataFrame({"ix": ix, "iy": iy}).groupby(["ix", "iy"]).size().rename("trips").reset_index()
    g["x"], g["y"] = (g["ix"] + 0.5) * cell, (g["iy"] + 0.5) * cell
    g["trips_per_day"] = g["trips"] / n_days(trips)
    return g


def hotspots(trips, cell=400, top_share=0.5, hours=None, proj=None, min_trips=1):
    """النقاط الساخنة: أصغر مجموعة خلايا تغطي top_share من الرحلات، مدموجة بالجوار (8 اتجاهات). كل نقطة: رتبة، رحلات/يوم، ساعة الذروة."""
    g = grid_demand(trips, cell, hours).sort_values("trips", ascending=False)
    cum = g["trips"].cumsum() / g["trips"].sum()
    hot = g[(cum.shift(fill_value=0) < top_share) & (g["trips"] >= min_trips)].copy()
    if hot.empty:
        return pd.DataFrame()
    ix0, iy0 = hot["ix"].min(), hot["iy"].min()
    mat = np.zeros((hot["ix"].max() - ix0 + 1, hot["iy"].max() - iy0 + 1), int)
    mat[hot["ix"] - ix0, hot["iy"] - iy0] = 1
    lab, n = label(mat, structure=np.ones((3, 3)))
    hot["cluster"] = lab[hot["ix"] - ix0, hot["iy"] - iy0]
    t = trips if hours is None else trips[trips["hour"].isin(hours)]
    tix, tiy, _, _ = geo.grid_cells(t["px"], t["py"], cell)
    key = pd.Series(list(zip(tix, tiy)), index=t.index)
    cl_of = {(r.ix, r.iy): r.cluster for r in hot.itertuples()}
    cl = key.map(cl_of)
    rows = []
    for c, g2 in hot.groupby("cluster"):
        w = g2["trips"].values
        th = t[cl == c]
        rows.append(
            dict(
                x=float(np.average(g2["x"], weights=w)),
                y=float(np.average(g2["y"], weights=w)),
                cells=len(g2),
                trips_per_day=float(w.sum() / n_days(trips)),
                share_pct=float(100 * w.sum() / len(t)),
                peak_hour=int(th["hour"].mode().iat[0]) if len(th) else -1,
            )
        )
    out = pd.DataFrame(rows).sort_values("trips_per_day", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    if proj is not None:
        out["lon"], out["lat"] = proj.lonlat(out["x"], out["y"])
    return out


def od_flows(trips, zones, top=30):
    """أعلى تدفقات الأصل→الوجهة بين مناطق (أقرب منطقة لكل طرف). zones فيه x,y,name."""
    if "dx" not in trips:
        return pd.DataFrame()
    zxy = zones[["x", "y"]].to_numpy()
    _, o = geo.nearest(trips[["px", "py"]].to_numpy(), zxy)
    _, d = geo.nearest(trips[["dx", "dy"]].to_numpy(), zxy)
    f = pd.DataFrame({"o": o, "d": d}).groupby(["o", "d"]).size().rename("trips").reset_index()
    f = f[f["o"] != f["d"]].sort_values("trips", ascending=False).head(top)
    f["from"] = zones["name"].values[f["o"]]
    f["to"] = zones["name"].values[f["d"]]
    f["trips_per_day"] = f["trips"] / n_days(trips)
    return f[["from", "to", "trips", "trips_per_day"]].reset_index(drop=True)
