"""نمذجة الطلب: توليد الرحلات وجذبها (نموذج الجاذبية) وتقدير الركاب على النقل العام."""

import numpy as np
import pandas as pd

from transport_hub.core import geo


def zone_attraction(pop, poi, job_weight=1.0, poi_scale=100.0):
    """جاذبية كل منطقة = الوظائف + مجموع أوزان نقاط الجذب فيها (كل نقطة تُسند لأقرب منطقة) × poi_scale."""
    a = pop["jobs"].to_numpy(float) * job_weight if "jobs" in pop else np.zeros(len(pop))
    a = a.copy()
    if poi is not None and len(poi):
        _, zi = geo.nearest(poi[["x", "y"]].to_numpy(), pop[["x", "y"]].to_numpy())
        a += np.bincount(zi, weights=poi["weight"].to_numpy(float), minlength=len(pop)) * poi_scale
    return a


def gravity(pop, poi, beta=0.25, trip_rate=2.5, top=40, max_zones=3000):
    """نموذج جاذبية أحادي القيد: T_ij = P_i · A_j·exp(-β d_ij) / Σ_k A_k·exp(-β d_ik)، d بالكم (بعد التعرج).
    P_i = السكان × معدل الرحلات اليومية للفرد. يرجع (جدول المناطق: production, attraction, avg_trip_km)، (أعلى تدفقات)."""
    n = len(pop)
    if n > max_zones:
        raise ValueError(f"عدد المناطق {n} أكبر من {max_zones}: اجمّع المناطق أو ارفع الحد")
    xy = pop[["x", "y"]].to_numpy()
    A = zone_attraction(pop, poi)
    P = pop["pop"].to_numpy(float) * trip_rate
    d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1]) * geo.DETOUR / 1000 + 0.3
    f = A[None, :] * np.exp(-beta * d)
    np.fill_diagonal(f, f.diagonal() * 0.5)  # الرحلات داخل المنطقة أقل
    T = P[:, None] * f / f.sum(axis=1, keepdims=True).clip(1e-9)
    out = pop[["zone_id", "name", "district", "x", "y"]].copy()
    out["production"], out["attraction_score"] = P, A
    out["attracted_trips"] = T.sum(axis=0)
    out["avg_trip_km"] = (T * d).sum(axis=1) / T.sum(axis=1).clip(1e-9)
    idx = np.dstack(np.unravel_index(np.argsort(-T, axis=None)[: top * 3], T.shape))[0]
    rows = [dict(**{"from": pop["name"].iat[i], "to": pop["name"].iat[j]}, trips=float(T[i, j]), km=float(d[i, j])) for i, j in idx if i != j][:top]
    return out, pd.DataFrame(rows), T


def transit_share(access_index, max_share=0.35, half=8.0):
    """حصة النقل العام من الرحلات كدالة لمؤشر مستوى الخدمة (منحنى تشبّع). تقديري ويحتاج معايرة بمسح ركاب."""
    ai = np.asarray(access_index, float)
    return max_share * ai / (ai + half)
