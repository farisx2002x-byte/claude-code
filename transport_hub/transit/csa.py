"""الوصول بالنقل العام بزمن حقيقي (Connection Scan): أقرب وصول من نقطة لكل المحطات، وعدد الفرص خلال T دقيقة."""

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from transport_hub.core import geo

INF = 1e18
TRANSFER_WALK_M = 300  # مشي بين محطتين قريبتين للتبديل (مسافة فعلية)
MIN_TRANSFER_S = 60


class Router:
    def __init__(self, feed, proj, weekday=None):
        from transport_hub.transit.gtfs import active_trips

        tr = active_trips(feed, weekday)
        st = feed.stop_times[feed.stop_times["trip_id"].isin(tr["trip_id"])]
        st = st.sort_values(["trip_id", "stop_sequence"])
        nxt = st.groupby("trip_id").shift(-1)
        m = nxt["stop_id"].notna()
        conn = (
            pd.DataFrame(
                {
                    "trip": st.loc[m, "trip_id"].values,
                    "from": st.loc[m, "stop_id"].values,
                    "to": nxt.loc[m, "stop_id"].values,
                    "dep": st.loc[m, "dep"].values,
                    "arr": nxt.loc[m, "arr"].values,
                }
            )
            .sort_values("dep")
            .reset_index(drop=True)
        )
        self.stops = feed.stops.dropna(subset=["stop_lat", "stop_lon"]).reset_index(drop=True)
        self.stops["x"], self.stops["y"] = proj.xy(self.stops["stop_lon"], self.stops["stop_lat"])
        self.sid = {s: i for i, s in enumerate(self.stops["stop_id"])}
        keep = conn["from"].isin(self.sid) & conn["to"].isin(self.sid)
        conn = conn[keep]
        self.c_from = conn["from"].map(self.sid).to_numpy()
        self.c_to = conn["to"].map(self.sid).to_numpy()
        self.c_dep = conn["dep"].to_numpy(float)
        self.c_arr = conn["arr"].to_numpy(float)
        tcode = {t: i for i, t in enumerate(conn["trip"].unique())}
        self.c_trip = conn["trip"].map(tcode).to_numpy()
        self.n_trips = len(tcode)
        self.tree = cKDTree(self.stops[["x", "y"]].to_numpy())
        # أقدام التبديل
        pairs = self.tree.query_pairs(TRANSFER_WALK_M / geo.DETOUR, output_type="ndarray")
        self.foot = {}
        xy = self.stops[["x", "y"]].to_numpy()
        for a, b in pairs:
            w = float(np.hypot(*(xy[a] - xy[b])) * geo.DETOUR / (geo.WALK_KMH * 1000 / 3600))
            self.foot.setdefault(a, []).append((b, w))
            self.foot.setdefault(b, []).append((a, w))
        self.proj = proj

    def earliest_arrival(self, x, y, t0, max_walk_m=800, horizon_s=5400):
        """أقرب وقت وصول لكل محطة من نقطة (x,y) تنطلق عند t0 (ثواني). يرجع مصفوفة بحجم المحطات."""
        arr = np.full(len(self.stops), INF)
        for j in self.tree.query_ball_point([x, y], max_walk_m / geo.DETOUR):
            d = np.hypot(self.stops["x"].iat[j] - x, self.stops["y"].iat[j] - y) * geo.DETOUR
            arr[j] = min(arr[j], t0 + d / (geo.WALK_KMH * 1000 / 3600))
        boarded = np.zeros(self.n_trips, bool)
        end = t0 + horizon_s
        start = int(np.searchsorted(self.c_dep, t0))
        foot = self.foot
        for k in range(start, len(self.c_dep)):
            dep = self.c_dep[k]
            if dep > end:
                break
            tr = self.c_trip[k]
            if boarded[tr] or arr[self.c_from[k]] <= dep:
                boarded[tr] = True
                to, a = self.c_to[k], self.c_arr[k]
                if a < arr[to]:
                    arr[to] = a
                    for n, w in foot.get(to, ()):
                        if a + w + MIN_TRANSFER_S < arr[n]:
                            arr[n] = a + w + MIN_TRANSFER_S
        return arr

    def reachable_points(self, arr, pts_xy, t0, minutes, max_walk_m=800):
        """أي نقاط (x,y) يمكن الوصول لها خلال minutes دقيقة (النزول في محطة ثم المشي)."""
        limit = t0 + minutes * 60
        ok = np.zeros(len(pts_xy), bool)
        good = np.where(arr <= limit)[0]
        if len(good) == 0:
            return ok
        tree = cKDTree(self.stops[["x", "y"]].to_numpy()[good])
        near = tree.query_ball_point(pts_xy, max_walk_m / geo.DETOUR)
        speed = geo.WALK_KMH * 1000 / 3600
        xy = self.stops[["x", "y"]].to_numpy()
        for i, nb in enumerate(near):
            for jj in nb:
                j = good[jj]
                d = np.hypot(*(xy[j] - pts_xy[i])) * geo.DETOUR
                if arr[j] + d / speed <= limit:
                    ok[i] = True
                    break
        return ok


def opportunities(router, origins, dest, t0_h=8.0, minutes=45, value_cols=("pop",), max_origins=400, seed=0):
    """لكل نقطة انطلاق: مجموع الفرص (السكان/الوظائف/نقاط الجذب الموزونة) الممكن بلوغها بالنقل العام خلال minutes.
    origins/dest: DataFrame فيه x,y. للأحجام الكبيرة نعيّن عينة (max_origins) ونقدّر الباقي بأقرب نقطة."""
    t0 = t0_h * 3600
    n = len(origins)
    idx = np.arange(n) if n <= max_origins else np.sort(np.random.default_rng(seed).choice(n, max_origins, replace=False))
    pts = dest[["x", "y"]].to_numpy()
    res = {c: np.full(n, np.nan) for c in value_cols}
    for i in idx:
        arr = router.earliest_arrival(origins["x"].iat[i], origins["y"].iat[i], t0, horizon_s=minutes * 60 + 600)
        ok = router.reachable_points(arr, pts, t0, minutes)
        for c in value_cols:
            res[c][i] = dest.loc[ok, c].sum()
    out = origins.copy()
    for c in value_cols:
        out[f"reach_{c}_{minutes}"] = res[c]
    if len(idx) < n:  # تقدير باقي النقاط من أقرب نقطة محسوبة
        tree = cKDTree(origins[["x", "y"]].to_numpy()[idx])
        _, nn = tree.query(origins[["x", "y"]].to_numpy())
        for c in value_cols:
            col = f"reach_{c}_{minutes}"
            out[col] = out[col].fillna(pd.Series(res[c][idx][nn], index=out.index))
    return out
