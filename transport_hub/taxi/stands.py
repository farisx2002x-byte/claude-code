"""مواقع مواقف التاكسي: تعظيم عدد الالتقاطات المخدومة ضمن مسافة مشي."""

import numpy as np
import pandas as pd

from transport_hub.core import geo
from transport_hub.core.access import Access
from transport_hub.siting import coverage as SC
from transport_hub.taxi.demand import n_days


def suggest_stands(trips, existing_xy, k=8, radius_m=300, cell=200, proj=None, hours=None, access=None):
    """يختار k موقفاً جديداً يعظم الالتقاطات المخدومة (ضمن radius_m مشي) غير المغطاة بالمواقف الحالية."""
    access = access or Access()
    t = trips if hours is None else trips[trips["hour"].isin(hours)]
    ix, iy, cx, cy = geo.grid_cells(t["px"], t["py"], cell)
    g = pd.DataFrame({"x": cx, "y": cy}).groupby(["x", "y"]).size().rename("n").reset_index()
    r = radius_m / geo.DETOUR
    cand = g[["x", "y"]].to_numpy()
    covered = None
    if existing_xy is not None and len(existing_xy):
        d0, _ = access.walk_nearest(cand, np.asarray(existing_xy, float), limit=radius_m * 2)
        covered = d0 <= radius_m
    lists = access.cover_lists(cand, cand, radius_m)
    sel, (before, after) = SC.max_coverage(cand, g["n"].to_numpy(float), cand, r, k, lists=lists, covered=covered)
    d = n_days(trips)
    sel["trips_per_day"] = sel["gain"] / d
    if proj is not None and len(sel):
        sel["lon"], sel["lat"] = proj.lonlat(sel["x"], sel["y"])
    return sel, (before, after)


def stand_coverage(trips, stands_xy, radius_m=300, access=None):
    """نسبة الالتقاطات القريبة من موقف موجود."""
    if stands_xy is None or len(stands_xy) == 0:
        return 0.0
    d, _ = (access or Access()).walk_nearest(trips[["px", "py"]].to_numpy(), np.asarray(stands_xy, float), limit=radius_m * 2)
    return float(100 * np.mean(d <= radius_m))
