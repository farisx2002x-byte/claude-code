"""فحص جودة البيانات: لكل فحص العدد والنسبة والأهمية والإجراء المقترح."""
import pandas as pd

import config as C


def _row(name, n, total, importance, action):
    return dict(الفحص=name, العدد=int(n), النسبة=round(100 * n / total, 1) if total else 0.0,
                الأهمية=importance, الإجراء_المقترح=action)


def check(df):
    t = len(df)
    lon0, lat0, lon1, lat1 = C.JEDDAH_BBOX
    dup = df.duplicated(subset=["lon", "lat"], keep=False)
    rows = [
        _row("نقاط خارج جدة", ((df.lon < lon0) | (df.lon > lon1) | (df.lat < lat0) | (df.lat > lat1)).sum(), t,
             "عالية", "تصحيح إحداثيات البيت أو استبعاد الطالب"),
        _row("إحداثيات مكررة (غالباً إخوان في نفس البيت)", dup.sum(), t, "منخفضة", "مقبول؛ تأكد إن الإخوان ينحسبون مرة وحدة بالمسار"),
        _row("مرحلة غير معروفة", (df.stage == "غير معروف").sum(), t, "متوسطة", "تصحيح المرحلة (تؤثر على معامل المشي)"),
        _row("مدرسة غير مربوطة", (df.school_match == "none").sum(), t, "عالية", "إضافة الربط في data/school_lookup.csv"),
        _row("ربط مدرسة يحتاج تأكيد", (df.school_match == "confirm").sum(), t, "متوسطة", "تأكيد الاسم الرسمي مع المدرسة"),
        _row("مدرسة بدون موقع", (df.school_match == "nolocation").sum(), t, "عالية", "إضافة ملف KML لموقع المدرسة"),
        _row("بيت بعيد عن الشارع المقاس (> 150 م)", (df.snap_m_L > C.CONF_LOW_SNAP).sum(), t, "عالية", "تحقق ميداني أو تصحيح إحداثيات البيت"),
        _row("بيت بين 60 و150 م من الشارع", ((df.snap_m_L > C.CONF_MID_SNAP) & (df.snap_m_L <= C.CONF_LOW_SNAP)).sum(), t, "متوسطة", "مراجعة عينة"),
        _row("بيت داخل قطعة كبيرة مجهولة", df.in_unknown.sum(), t, "متوسطة", "النتيجة تقديرية؛ تحتاج صور جوية"),
        _row("مسافة للمدرسة أكثر من 20 كم", (df.dist_school_m > 20000).sum(), t, "عالية", "غالباً خطأ في إحداثيات البيت أو ربط المدرسة"),
        _row("لا تصله أي مركبة", (~(df.access_L.fillna(False).astype(bool) | df.access_M.fillna(False).astype(bool) | df.access_S.fillna(False).astype(bool))).sum(), t, "عالية", "نقطة تجميع أو ترتيب خاص"),
    ]
    return pd.DataFrame(rows)
