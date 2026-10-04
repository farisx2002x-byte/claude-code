"""حجم أسطول التاكسي ومؤشرات الأداء، مع نموذج طوابير (Erlang C) لتقدير الانتظار."""
import math

import numpy as np
import pandas as pd

from transport_hub.taxi.demand import n_days


def erlang_c(c, a):
    """احتمال انتظار الراكب في نظام M/M/c (c مركبات، a = حمل الطلب بوحدة Erlang). a ≥ c → 1."""
    if a >= c:
        return 1.0
    s, term = 0.0, 1.0
    for k in range(c):
        s += term
        term *= a / (k + 1)
    top = term * c / (c - a)
    return top / (s + top)


def avg_wait_min(vehicles, rate_per_hr, service_min):
    """متوسط انتظار الراكب (دقيقة) إذا كل مركبة تخدم رحلة مدتها service_min (تشمل الوصول للراكب)."""
    if vehicles <= 0:
        return float("inf")
    a = rate_per_hr * service_min / 60
    if a >= vehicles:
        return float("inf")
    return erlang_c(vehicles, a) / (vehicles * 60 / service_min - rate_per_hr) * 60


def vehicles_for_wait(rate_per_hr, service_min, target_wait_min):
    """أقل عدد مركبات يحقق متوسط انتظار ≤ الهدف."""
    c = max(int(math.ceil(rate_per_hr * service_min / 60)) + 1, 1)
    while avg_wait_min(c, rate_per_hr, service_min) > target_wait_min and c < 100000:
        c += 1
    return c


def kpis(trips, fleet_size=None):
    d = n_days(trips)
    fs = fleet_size or (trips["vehicle_id"].nunique() if "vehicle_id" in trips else None)
    out = {"الرحلات/يوم": round(len(trips) / d, 1)}
    if "fare" in trips:
        out["متوسط الأجرة"] = round(float(trips["fare"].mean()), 2)
    if "distance_km" in trips:
        out["متوسط المسافة كم"] = round(float(trips["distance_km"].mean()), 2)
    if "duration_min" in trips:
        out["متوسط مدة الرحلة د"] = round(float(trips["duration_min"].mean()), 1)
    if "wait_min" in trips:
        out["متوسط الانتظار د"] = round(float(trips["wait_min"].mean()), 1)
    if fs:
        out["حجم الأسطول"] = int(fs)
        out["رحلات/مركبة/يوم"] = round(len(trips) / d / fs, 2)
        if "duration_min" in trips:
            out["نسبة الإشغال (وقت الرحلات)"] = round(float(trips["duration_min"].sum() / d / (fs * 24 * 60)), 3)
        if "fare" in trips:
            out["إيراد/مركبة/يوم"] = round(float(trips["fare"].sum() / d / fs), 1)
    return out


def fleet_by_hour(trips, target_wait_min=5.0, deadhead_min=6.0, max_util=0.75):
    """المركبات المطلوبة لكل ساعة: (أ) حسب الانتظار المستهدف بنموذج Erlang C، (ب) حسب سقف الإشغال. نأخذ الأكبر.
    deadhead_min: متوسط وقت الوصول للراكب (يُضاف لمدة الرحلة)."""
    d = n_days(trips)
    dur = float(trips["duration_min"].mean()) if "duration_min" in trips else 15.0
    svc = dur + deadhead_min
    rows = []
    for h in range(24):
        rate = (trips["hour"] == h).sum() / d
        if rate == 0:
            rows.append(dict(hour=h, trips=0.0, needed_wait=0, needed_util=0, needed=0))
            continue
        nw = vehicles_for_wait(rate, svc, target_wait_min)
        nu = math.ceil(rate * svc / 60 / max_util)
        rows.append(dict(hour=h, trips=rate, needed_wait=nw, needed_util=nu, needed=max(nw, nu)))
    out = pd.DataFrame(rows)
    return out
