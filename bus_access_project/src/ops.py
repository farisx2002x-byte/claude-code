"""المؤشرات التشغيلية: كم في اليوم، ساعات التشغيل، الوقود والتكلفة وCO2، والمطلوب مقابل الحالي."""
import numpy as np
import pandas as pd

import config as C


def route_ops(routes):
    """يضيف أعمدة التشغيل لجدول المسارات."""
    r = routes.copy()
    if r.empty:
        return r
    r["km_day"] = r["length_km"] * C.TRIPS_PER_DAY
    r["hours_day"] = r["duration_min"] / 60.0 * C.TRIPS_PER_DAY
    r["fuel_l_day"] = [km * C.FUEL_L_PER_100KM[v] / 100.0 for km, v in zip(r["km_day"], r["vk"])]
    r["fuel_sar_year"] = r["fuel_l_day"] * C.SCHOOL_DAYS * C.FUEL_PRICE_SAR
    r["co2_t_year"] = r["fuel_l_day"] * C.SCHOOL_DAYS * C.CO2_KG_PER_L / 1000.0
    return r


def school_ops(routes, fleet_by_school):
    """مؤشرات لكل مدرسة: المطلوب (لكل نوع وإجمالي) مقابل الحالي، ومتوسط الرحلة وأطولها، وأبكر انطلاق."""
    r = route_ops(routes)
    if r.empty:
        return pd.DataFrame()
    g = r.groupby("school")
    out = pd.DataFrame({
        "need_large": g["vk"].apply(lambda s: int((s == "large").sum())),
        "need_medium": g["vk"].apply(lambda s: int((s == "medium").sum())),
        "need_small": g["vk"].apply(lambda s: int((s == "small").sum())),
        "students": g["students"].sum(),
        "km_day": g["km_day"].sum(), "hours_day": g["hours_day"].sum(),
        "fuel_sar_year": g["fuel_sar_year"].sum(), "co2_t_year": g["co2_t_year"].sum(),
        "avg_ride_min": g.apply(lambda d: np.average(d["longest_ride_min"], weights=d["students"]), include_groups=False),
        "max_ride_min": g["longest_ride_min"].max(),
        "earliest_start": g["start_time"].min(),
    })
    out["need_total"] = out[["need_large", "need_medium", "need_small"]].sum(axis=1)
    f = fleet_by_school.set_index("school")[["buses_large", "buses_medium"]] if len(fleet_by_school) else None
    if f is not None:
        out = out.join(f).fillna({"buses_large": 0, "buses_medium": 0})
        out["current_total"] = out["buses_large"] + out["buses_medium"]
        out["gap"] = out["need_total"] - out["current_total"]
    return out.reset_index()


def totals(routes, assigned_students):
    r = route_ops(routes)
    if r.empty:
        return {}
    return dict(routes=len(r), large=int((r.vk == "large").sum()), medium=int((r.vk == "medium").sum()),
                small=int((r.vk == "small").sum()), km_day=float(r.km_day.sum()),
                fuel_sar_year=float(r.fuel_sar_year.sum()), co2_t_year=float(r.co2_t_year.sum()),
                avg_ride_min=float(np.average(r.longest_ride_min, weights=r.students)),
                students=int(assigned_students))
