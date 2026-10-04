"""مواقع مواقف التاكسي: تعظيم عدد الالتقاطات المخدومة ضمن مسافة مشي."""
import numpy as np
import pandas as pd

from transport_hub.core import geo
from transport_hub.siting import coverage as SC
from transport_hub.taxi.demand import n_days


def suggest_stands(trips, existing_xy, k=8, radius_m=300, cell=200, proj=None, hours=None):
    """يختار k موقفاً جديداً يعظم الالتقاطات المخدومة (ضمن radius_m مشي) غير المغطاة بالمواقف الحالية."""
    t = trips if hours is None else trips[trips["hour"].isin(hours)]
    ix, iy, cx, cy = geo.grid_cells(t["px"], t["py"], cell)
    g = pd.DataFrame({"x": cx, "y": cy}).groupby(["x", "y"]).size().rename("n").reset_index()
    r = radius_m / geo.DETOUR
    cand = g[["x", "y"]].to_numpy()
    sel, (before, after) = SC.max_coverage(cand, g["n"].to_numpy(float), cand, r, k, existing_xy=existing_xy)
    d = n_days(trips)
    sel["trips_per_day"] = sel["gain"] / d
    if proj is not None and len(sel):
        sel["lon"], sel["lat"] = proj.lonlat(sel["x"], sel["y"])
    return sel, (before, after)


def stand_coverage(trips, stands_xy, radius_m=300):
    """نسبة الالتقاطات القريبة من موقف موجود."""
    if stands_xy is None or len(stands_xy) == 0:
        return 0.0
    d, _ = geo.nearest(trips[["px", "py"]].to_numpy(), np.asarray(stands_xy))
    return float(100 * np.mean(d * geo.DETOUR <= radius_m))
