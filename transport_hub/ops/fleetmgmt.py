"""إدارة الأسطول: سجل المركبات، الصيانة الدورية، العمر، والتحول للكهرباء (احتياج الطاقة وجدوى الشحن والتكلفة)."""

from datetime import date

import numpy as np
import pandas as pd

REG_COLS = ["vehicle_id", "type", "seats", "year", "odometer_km", "last_service_km", "last_service_date"]
SERVICE_KM, SERVICE_DAYS = 10_000, 180


def clean_register(df):
    miss = [c for c in REG_COLS if c not in df.columns]
    if miss:
        raise ValueError(f"سجل الأسطول: أعمدة ناقصة {miss}. المطلوب {REG_COLS}")
    d = df.copy()
    d["last_service_date"] = pd.to_datetime(d["last_service_date"], errors="coerce")
    for c in ("seats", "year", "odometer_km", "last_service_km"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def maintenance(reg, km_per_day, today=None, service_km=SERVICE_KM, service_days=SERVICE_DAYS, soon_km=1500, soon_days=21):
    """حالة الصيانة لكل مركبة: متأخرة / قريبة / سليمة، والتاريخ المتوقع للصيانة القادمة حسب معدل الكيلومترات اليومي.
    km_per_day: رقم أو dict مركبة→كم/يوم."""
    today = pd.Timestamp(today or date.today())
    d = reg.copy()
    rate = d["vehicle_id"].map(km_per_day).fillna(np.nanmean(list(km_per_day.values()))) if isinstance(km_per_day, dict) else km_per_day
    d["km_since"] = d["odometer_km"] - d["last_service_km"]
    d["days_since"] = (today - d["last_service_date"]).dt.days
    d["km_left"] = service_km - d["km_since"]
    d["days_left"] = service_days - d["days_since"]
    d["status"] = np.where(
        (d["km_left"] < 0) | (d["days_left"] < 0), "متأخرة", np.where((d["km_left"] < soon_km) | (d["days_left"] < soon_days), "قريبة", "سليمة")
    )
    eta_days = np.minimum(d["km_left"].clip(lower=0) / np.maximum(rate, 1), d["days_left"].clip(lower=0))
    d["next_service"] = (today + pd.to_timedelta(eta_days, "D")).dt.date
    d["age"] = today.year - d["year"]
    return d


def age_profile(reg, today=None):
    y = pd.Timestamp(today or date.today()).year
    age = y - reg["year"]
    return (
        pd.cut(age, [-1, 2, 5, 8, 12, 100], labels=["0-2", "3-5", "6-8", "9-12", "13+"])
        .value_counts()
        .sort_index()
        .rename_axis("العمر")
        .reset_index(name="العدد")
    )


def ev_feasibility(blocks, kwh_per_km=1.6, battery_kwh=350, usable=0.8, reserve=0.1, charge_kw=150, window_h=6.0, dead_km=None):
    """جدوى تحويل كل مركبة (كتلة تشغيل) لكهربائية: الطاقة اليومية مقابل البطارية القابلة للاستخدام، واحتياج الشحن الليلي.
    blocks: جدول رحلات المركبات (فيه vehicle, km). يرجع (جدول المركبات، ملخص)."""
    v = blocks.groupby("vehicle")["km"].sum().rename("service_km").reset_index()
    v["km"] = v["service_km"] + (dead_km.reindex(v["vehicle"]).fillna(0).to_numpy() if dead_km is not None else 0)
    v["kwh_day"] = v["km"] * kwh_per_km
    usable_kwh = battery_kwh * (usable - reserve)
    v["feasible"] = v["kwh_day"] <= usable_kwh
    v["needs_midday_charge_kwh"] = (v["kwh_day"] - usable_kwh).clip(lower=0)
    v["charge_h"] = v["kwh_day"] / charge_kw
    chargers = int(np.ceil(v["charge_h"].sum() / window_h))
    summary = dict(
        vehicles=len(v),
        feasible=int(v["feasible"].sum()),
        feasible_pct=round(100 * float(v["feasible"].mean()), 1),
        energy_mwh_day=round(float(v["kwh_day"].sum()) / 1000, 1),
        chargers_needed=chargers,
        depot_peak_kw=round(chargers * charge_kw),
        usable_kwh=round(usable_kwh),
    )
    return v, summary


DIESEL_DEFAULT = dict(price=650_000, l_100=30, fuel_price=1.66, maint_km=0.9)
EV_DEFAULT = dict(price=1_450_000, kwh_km=1.6, kwh_price=0.18, maint_km=0.45, charger=120_000)


def tco(
    km_year,
    years,
    diesel=None,
    ev=None,
    co2_diesel_kg_l=2.68,
    co2_grid_kg_kwh=0.55,
    discount=0.05,
):
    """مقارنة التكلفة الإجمالية (TCO) لمركبة واحدة بين الديزل والكهرباء على مدى years، مع القيمة الحالية والانبعاثات. قيم تقديرية."""
    diesel = {**DIESEL_DEFAULT, **(diesel or {})}
    ev = {**EV_DEFAULT, **(ev or {})}
    f = sum(1 / (1 + discount) ** t for t in range(1, years + 1))
    d_op = km_year * (diesel["l_100"] / 100 * diesel["fuel_price"] + diesel["maint_km"])
    e_op = km_year * (ev["kwh_km"] * ev["kwh_price"] + ev["maint_km"])
    out = dict(diesel_total=diesel["price"] + d_op * f, ev_total=ev["price"] + ev["charger"] + e_op * f)
    out["saving"] = out["diesel_total"] - out["ev_total"]
    out["co2_saving_t_year"] = (km_year * diesel["l_100"] / 100 * co2_diesel_kg_l - km_year * ev["kwh_km"] * co2_grid_kg_kwh) / 1000
    payback = np.nan
    extra = ev["price"] + ev["charger"] - diesel["price"]
    if d_op > e_op:
        payback = extra / (d_op - e_op)
    out["payback_years"] = payback
    return {k: float(v) for k, v in out.items()}
