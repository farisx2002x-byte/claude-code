"""الوصول بالنقل العام بزمن حقيقي (Connection Scan): أقرب وصول من نقطة لكل المحطات، وعدد الفرص خلال T دقيقة."""

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from transport_hub.core import geo
from transport_hub.core.access import Access

INF = 1e18
TRANSFER_WALK_M = 300  # مشي بين محطتين قريبتين للتبديل (مسافة فعلية)
MIN_TRANSFER_S = 60


class Router:
    def __init__(self, feed, proj, weekday=None, access=None):
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
        self.access = access or Access()
        self.speed = geo.WALK_KMH * 1000 / 3600
        xy = self.stops[["x", "y"]].to_numpy()
        # أقدام التبديل: محطات ضمن مسافة مشي TRANSFER_WALK_M (على الشوارع إن توفرت)
        t, s_, d = self.access.cover(xy, xy, TRANSFER_WALK_M)
        self.foot = {}
        for ti, si, di in zip(t, s_, d, strict=True):
            if ti != si:
                self.foot.setdefault(int(si), []).append((int(ti), float(di / self.speed)))
        self._dest_cache = {}
        self.proj = proj

    def earliest_arrival(self, x, y, t0, max_walk_m=800, horizon_s=5400):
        """أقرب وقت وصول لكل محطة من نقطة (x,y) تنطلق عند t0 (ثواني). يرجع مصفوفة بحجم المحطات."""
        arr = np.full(len(self.stops), INF)
        t_, s_, d_ = self.access.cover(self.stops[["x", "y"]].to_numpy(), np.array([[x, y]]), max_walk_m)  # من النقطة إلى المحطات القريبة
        for j, d in zip(s_, d_, strict=True):
            arr[j] = min(arr[j], t0 + d / self.speed)
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

    def _dest_index(self, pts_xy, max_walk_m):
        """لكل محطة: النقاط (والمسافات) التي يصلها الراكب مشياً منها. تُحسب مرة وتُخزَّن لأن المحطات والنقاط ثابتة بين الاستعلامات."""
        pts_xy = np.asarray(pts_xy, float)
        key = (hash(pts_xy.tobytes()), max_walk_m)
        if key not in self._dest_cache:
            t, s_, d = self.access.cover(pts_xy, self.stops[["x", "y"]].to_numpy(), max_walk_m)
            idx = {}
            for ti, si, di in zip(t, s_, d, strict=True):
                idx.setdefault(int(ti), ([], []))
                idx[int(ti)][0].append(int(si))
                idx[int(ti)][1].append(float(di))
            self._dest_cache[key] = {j: (np.array(a, int), np.array(b, float)) for j, (a, b) in idx.items()}
        return self._dest_cache[key]

    def reachable_points(self, arr, pts_xy, t0, minutes, max_walk_m=800):
        """أي نقاط (x,y) يمكن الوصول لها خلال minutes دقيقة (النزول في محطة ثم المشي)."""
        limit = t0 + minutes * 60
        ok = np.zeros(len(pts_xy), bool)
        index = self._dest_index(pts_xy, max_walk_m)
        for j in np.where(arr <= limit)[0]:
            hit = index.get(int(j))
            if hit is not None:
                ids, dist = hit
                ok[ids[arr[j] + dist / self.speed <= limit]] = True
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
