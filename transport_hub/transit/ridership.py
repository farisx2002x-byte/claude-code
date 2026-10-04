"""تقدير الركاب (أولي): الطلب على النقل العام لكل منطقة، وتوزيعه على المحطات والخطوط."""
import numpy as np
import pandas as pd

from transport_hub.core import demand as DM
from transport_hub.core import geo


def estimate(cov, stops, stop_route, trip_rate=2.5, max_share=0.35, half=8.0):
    """cov: مناطق فيها pop, access_index, x, y. يرجع (ركاب/يوم لكل منطقة، لكل محطة، لكل خط) كتقدير أولي.
    الركاب = السكان × معدل الرحلات × حصة النقل العام(مؤشر الخدمة). يوزَّع على أقرب محطة ثم على خطوطها بنسبة التردد."""
    z = cov.copy()
    z["pax_day"] = z["pop"] * trip_rate * DM.transit_share(z["access_index"], max_share, half) * 2    # ×2 للعودة
    d, si = geo.nearest(z[["x", "y"]].to_numpy(), stops[["x", "y"]].to_numpy())
    z["stop_id"] = stops["stop_id"].to_numpy()[si]
    z.loc[d * geo.DETOUR > 800, "pax_day"] = 0.0          # أبعد من 800 م: لا يستخدم
    by_stop = z.groupby("stop_id")["pax_day"].sum().rename("pax_day").reset_index()
    sr = stop_route.merge(by_stop, on="stop_id")
    sr["w"] = sr["deps_per_hour"] / sr.groupby("stop_id")["deps_per_hour"].transform("sum")
    sr["route_pax"] = sr["pax_day"] * sr["w"]
    by_route = sr.groupby("route_id")["route_pax"].sum().rename("pax_day").reset_index()
    return z, by_stop, by_route


def productivity(by_route, route_metrics, seats=72, turnover=2.0):
    """إنتاجية الخط: ركاب/كم وركاب/ساعة مركبة، ونسبة التحميل مقابل السعة (مقاعد × رحلات × معامل دوران الركاب)."""
    m = route_metrics.merge(by_route, on="route_id", how="left").fillna({"pax_day": 0})
    m["vehicle_km_day"] = m["length_km"] * m["trips_per_day"]
    m["vehicle_hours_day"] = m["run_time_min"] * m["trips_per_day"] / 60
    m["pax_per_km"] = m["pax_day"] / m["vehicle_km_day"].replace(0, np.nan)
    m["pax_per_vehicle_hour"] = m["pax_day"] / m["vehicle_hours_day"].replace(0, np.nan)
    m["capacity_pax_day"] = seats * m["trips_per_day"] * turnover
    m["load_ratio"] = m["pax_day"] / m["capacity_pax_day"].replace(0, np.nan)      # > 1 = الخدمة الحالية لا تكفي الطلب المقدّر
    return m
