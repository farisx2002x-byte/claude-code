"""مخططات البيانات المدخلة وقراءتها وفحصها: الطلب (السكان)، نقاط الجذب، رحلات التاكسي، المواقف الحالية."""
import numpy as np
import pandas as pd

POP_COLS = {"zone_id": "رقم المنطقة", "pop": "السكان", "lon": "خط الطول", "lat": "خط العرض"}
POP_OPT = {"name": "اسم المنطقة", "district": "الحي", "jobs": "الوظائف", "students": "الطلاب", "low_income": "نسبة ذوي الدخل المحدود (0-1)"}
POI_COLS = {"name": "الاسم", "category": "الفئة", "lon": "خط الطول", "lat": "خط العرض"}
TRIP_COLS = {"pickup_time": "وقت الالتقاط", "pickup_lon": "خط طول الالتقاط", "pickup_lat": "خط عرض الالتقاط"}
TRIP_OPT = {"dropoff_lon": "خط طول التوصيل", "dropoff_lat": "خط عرض التوصيل", "fare": "الأجرة", "distance_km": "المسافة كم",
            "duration_min": "المدة د", "vehicle_id": "رقم المركبة", "wait_min": "زمن الانتظار د"}

# أوزان جذب افتراضية لكل فئة (قابلة للتعديل من الواجهة): تمثّل حجم الرحلات التي تولّدها
POI_WEIGHTS = {
    "مستشفى": 8, "جامعة": 10, "مول": 9, "سوق": 6, "مدرسة": 4, "مسجد": 2, "مطار": 10,
    "محطة قطار": 10, "مبنى حكومي": 6, "مكاتب": 7, "ترفيه": 5, "فندق": 4, "أخرى": 3,
}


class DataError(ValueError):
    """خطأ في بيانات المدخلات برسالة عربية واضحة."""


def _need(df, cols, what):
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise DataError(f"{what}: أعمدة ناقصة {miss}. المطلوب: {list(cols)}")


def clean_population(df, proj):
    _need(df, POP_COLS, "ملف السكان")
    d = df.copy()
    d["pop"] = pd.to_numeric(d["pop"], errors="coerce")
    d = d.dropna(subset=["pop", "lon", "lat"])
    d = d[d["pop"] >= 0]
    for c, default in (("name", None), ("district", "غير محدد")):
        if c not in d:
            d[c] = d["zone_id"].astype(str) if c == "name" else default
    for c in ("jobs", "students"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0) if c in d else 0.0
    d["low_income"] = pd.to_numeric(d["low_income"], errors="coerce").fillna(0).clip(0, 1) if "low_income" in d else 0.0
    return proj.attach(d.reset_index(drop=True))


def clean_poi(df, proj, weights=None):
    _need(df, POI_COLS, "ملف نقاط الجذب")
    w = dict(POI_WEIGHTS, **(weights or {}))
    d = df.dropna(subset=["lon", "lat"]).copy().reset_index(drop=True)
    d["category"] = d["category"].fillna("أخرى").astype(str)
    if "weight" in d:
        d["weight"] = pd.to_numeric(d["weight"], errors="coerce")
    else:
        d["weight"] = np.nan
    d["weight"] = d["weight"].fillna(d["category"].map(w)).fillna(w["أخرى"])
    d.insert(0, "poi_id", np.arange(len(d)))
    return proj.attach(d)


def clean_trips(df, proj):
    _need(df, TRIP_COLS, "ملف رحلات التاكسي")
    d = df.copy()
    d["pickup_time"] = pd.to_datetime(d["pickup_time"], errors="coerce")
    d = d.dropna(subset=["pickup_time", "pickup_lon", "pickup_lat"]).reset_index(drop=True)
    d["hour"] = d["pickup_time"].dt.hour
    d["dow"] = d["pickup_time"].dt.dayofweek
    d["date"] = d["pickup_time"].dt.date
    d["px"], d["py"] = proj.xy(d["pickup_lon"], d["pickup_lat"])
    if {"dropoff_lon", "dropoff_lat"} <= set(d.columns):
        d["dx"], d["dy"] = proj.xy(d["dropoff_lon"], d["dropoff_lat"])
    for c in ("fare", "distance_km", "duration_min", "wait_min"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def quality_report(pop=None, poi=None, trips=None, gtfs_report=None):
    """جدول فحص جودة لكل مجموعة بيانات محمّلة."""
    rows = []
    if pop is not None:
        rows.append(("السكان", "عدد المناطق", len(pop), ""))
        rows.append(("السكان", "إجمالي السكان", int(pop["pop"].sum()), ""))
        rows.append(("السكان", "مناطق بسكان صفر", int((pop["pop"] == 0).sum()), "تحقق من البيانات" if (pop["pop"] == 0).any() else ""))
    if poi is not None:
        rows.append(("نقاط الجذب", "عدد النقاط", len(poi), ""))
        rows.append(("نقاط الجذب", "الفئات", poi["category"].nunique(), ""))
    if trips is not None:
        rows.append(("التاكسي", "عدد الرحلات", len(trips), ""))
        rows.append(("التاكسي", "الأيام", trips["date"].nunique(), ""))
        if "wait_min" not in trips:
            rows.append(("التاكسي", "زمن الانتظار", "غير متوفر", "التقدير يعتمد على نموذج الطوابير"))
    if gtfs_report is not None:
        for r in gtfs_report.itertuples():
            rows.append(("النقل العام (GTFS)", r.الفحص, r.العدد, r.الأهمية))
    return pd.DataFrame(rows, columns=["المصدر", "الفحص", "القيمة", "ملاحظة"])
