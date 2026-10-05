"""توازن العرض والطلب للتاكسي وخطة إعادة التوزيع."""

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from transport_hub.core import geo
from transport_hub.core.access import Access


def zone_balance(trips, zones, hour, supply=None):
    """لكل منطقة في ساعة معينة: الطلب (التقاطات/يوم) والعرض (مركبات متاحة).
    supply: جدول اختياري (zone_index أو x,y, vehicles). لو ما وُجد نقدّر العرض بالتوصيلات (المركبات اللي أنهت رحلتها هناك)."""
    from transport_hub.taxi.demand import n_days

    d = n_days(trips)
    zxy = zones[["x", "y"]].to_numpy()
    t = trips[trips["hour"] == hour]
    _, zi = geo.nearest(t[["px", "py"]].to_numpy(), zxy) if len(t) else (None, np.array([], int))
    demand = np.bincount(zi, minlength=len(zones)) / d
    if supply is not None:
        _, si = geo.nearest(supply[["x", "y"]].to_numpy(), zxy)
        sup = np.bincount(si, weights=supply["vehicles"].to_numpy(float), minlength=len(zones))
    elif "dx" in trips:
        prev = trips[trips["hour"] == (hour - 1) % 24]
        _, di = geo.nearest(prev[["dx", "dy"]].to_numpy(), zxy) if len(prev) else (None, np.array([], int))
        sup = np.bincount(di, minlength=len(zones)) / d
    else:
        sup = np.full(len(zones), demand.mean())
    out = zones[["name", "x", "y"]].copy()
    out["demand"], out["supply"] = demand, sup
    out["balance"] = out["supply"] - out["demand"]
    out["ratio"] = np.where(out["demand"] > 0, out["supply"] / out["demand"].replace(0, np.nan), np.inf)
    return out


def rebalance_plan(bal, min_move=0.5, access=None):
    """خطة نقل المركبات من مناطق الفائض لمناطق العجز بأقل مسافة كلية (نقل خطي، HiGHS).
    تعيد: من، إلى، عدد المركبات، المسافة كم."""
    sur = bal[bal["balance"] > min_move]
    dfc = bal[bal["balance"] < -min_move]
    if sur.empty or dfc.empty:
        return pd.DataFrame(columns=["from", "to", "vehicles", "km"])
    s = np.floor(sur["balance"].to_numpy())
    dm = np.ceil(-dfc["balance"].to_numpy())
    D = (access or Access()).drive_matrix(sur[["x", "y"]].to_numpy(), dfc[["x", "y"]].to_numpy(), "length") / 1000  # كم على الشوارع إن توفرت
    ns, nd = D.shape
    c = D.ravel()
    A_ub, b_ub = [], []
    for i in range(ns):
        row = np.zeros(ns * nd)
        row[i * nd : (i + 1) * nd] = 1
        A_ub.append(row)
        b_ub.append(s[i])
    for j in range(nd):
        row = np.zeros(ns * nd)
        row[j::nd] = 1
        A_ub.append(row)
        b_ub.append(dm[j])
    total = min(s.sum(), dm.sum())
    res = linprog(c, A_ub=np.array(A_ub), b_ub=b_ub, A_eq=[np.ones(ns * nd)], b_eq=[total], bounds=(0, None), method="highs")
    if not res.success:
        return pd.DataFrame(columns=["from", "to", "vehicles", "km"])
    x = np.round(res.x.reshape(ns, nd)).astype(int)
    rows = [
        dict(**{"from": sur["name"].iat[i], "to": dfc["name"].iat[j]}, vehicles=int(x[i, j]), km=round(float(D[i, j]), 1))
        for i in range(ns)
        for j in range(nd)
        if x[i, j] > 0
    ]
    return pd.DataFrame(rows).sort_values("vehicles", ascending=False).reset_index(drop=True)
