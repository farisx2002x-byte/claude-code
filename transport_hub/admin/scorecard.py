"""بطاقة مؤشرات الأداء للإدارة: القيمة الفعلية مقابل المستهدف مع حالة (أخضر/أصفر/أحمر)."""

import pandas as pd

# (المفتاح, العنوان, الوحدة, المستهدف, الاتجاه: "up" الأعلى أفضل / "down" الأقل أفضل)
KPIS = [
    ("transit_cov400", "تغطية النقل العام (400 م)", "%", 60.0, "up"),
    ("transit_cov800", "تغطية النقل العام (800 م)", "%", 85.0, "up"),
    ("transit_ai", "متوسط مؤشر مستوى الخدمة", "", 5.0, "up"),
    ("transit_headway", "متوسط تردد الذروة", "د", 10.0, "down"),
    ("transit_no_service", "سكان بلا خدمة", "%", 10.0, "down"),
    ("taxi_wait", "متوسط انتظار التاكسي", "د", 5.0, "down"),
    ("taxi_util", "إشغال أسطول التاكسي", "%", 35.0, "up"),
    ("taxi_stand_cov", "تغطية مواقف التاكسي (300 م)", "%", 40.0, "up"),
    ("school_hard", "طلاب صعب وصول الباص الكبير لهم", "%", 10.0, "down"),
    ("school_nopath", "طلاب بدون مسار مدرسي", "%", 1.0, "down"),
    ("ops_otp", "الالتزام بالمواعيد", "%", 85.0, "up"),
    ("ops_ewt", "الانتظار الإضافي EWT", "د", 1.0, "down"),
    ("ops_crowded", "رحلات مزدحمة", "%", 5.0, "down"),
    ("fleet_overdue", "مركبات صيانتها متأخرة", "%", 5.0, "down"),
    ("equity_gini", "عدم المساواة في الخدمة (Gini)", "", 0.35, "down"),
]
AMBER = 0.15  # ضمن 15% من المستهدف = أصفر


def status(actual, target, direction):
    if actual is None or pd.isna(actual):
        return "غير متوفر"
    if direction == "up":
        if actual >= target:
            return "🟢"
        return "🟡" if actual >= target * (1 - AMBER) else "🔴"
    if actual <= target:
        return "🟢"
    return "🟡" if actual <= target * (1 + AMBER) else "🔴"


def build(values, targets=None):
    """values: dict مفتاح→قيمة. targets: dict مفتاح→مستهدف (يستبدل الافتراضي)."""
    targets = targets or {}
    rows = []
    for key, title, unit, tgt, d in KPIS:
        t = targets.get(key, tgt)
        v = values.get(key)
        rows.append(
            dict(
                المؤشر=title,
                الوحدة=unit,
                الفعلي=None if v is None else round(float(v), 2),
                المستهدف=t,
                الفرق=None if v is None else round(float(v) - t, 2),
                الحالة=status(v, t, d),
                key=key,
            )
        )
    return pd.DataFrame(rows)
