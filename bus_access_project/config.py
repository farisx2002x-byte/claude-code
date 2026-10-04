"""كل المسارات والإعدادات والافتراضات للمشروع (تُقرأ من settings.json لو موجود)."""
import json
import os
from pathlib import Path

VERSION = "3.0.0"

# ───────────── المسارات ─────────────
PROJECT = Path(__file__).resolve().parent
# مجلد البيانات الأساسية (يتغير بمتغير البيئة BUS_DATA_DIR)
DATA_DIR = Path(os.environ.get("BUS_DATA_DIR", r"C:\Users\welcome\Downloads"))
WORK = PROJECT / "work"
OUTPUT = PROJECT / "output"
LOCAL_DATA = PROJECT / "data"

STUDENTS_KML = DATA_DIR / "all_students.kml"
LANDUSE_GPKG = DATA_DIR / "Jeddah_LandUse_GIS" / "Jeddah_LandUse_Zones" / "Jeddah_LandUse_Zones.gpkg"
ROADS_ZIP = DATA_DIR / "السعودية" / "ksa_roads.zip"
ROADS_INNER = "KSA_Roads/Roads.shp"
FLEET_XLSX = DATA_DIR / "المدارس كاملة.xlsx"
SCHOOLS_ZIP = LOCAL_DATA / "schools.zip"
SCHOOL_LOOKUP = LOCAL_DATA / "school_lookup.csv"
FLEET_ALIAS = LOCAL_DATA / "fleet_alias.csv"
SETTINGS_JSON = PROJECT / "settings.json"

# ───────────── أعداد مرجعية (للتأكد من الملفات) ─────────────
EXPECTED = {"students": 8729, "zones": 111116, "districts": 226, "schools": 79, "fleet_buses": 201}

# ───────────── الإسقاط وحدود جدة ─────────────
CRS_UTM = "EPSG:32637"
JEDDAH_BBOX = (38.9, 21.1, 39.5, 22.0)  # lon_min, lat_min, lon_max, lat_max

# ───────────── المحرك: المربعات والراستر ─────────────
TILE = 2000          # حجم المربع (م)
HALO = 700           # هامش المربع (م)
RES = 1.0            # دقة الراستر (م)
BIG_POLY_M2 = 200_000   # القطعة الأكبر من كذا = مجهولة (مخطط بدون شوارع داخلية)
OPEN_EDT = 35        # الفراغ الأبعد من 35 م عن أي قطعة = أرض فضاء
PARKING_WORDS = ("مواقف",)  # قطع تُستثنى من العوائق
SCHOOL_TILE_RING = 1  # إضافة مربعات المدارس وجيرانها (3×3)

# عرض الطرق المفترض (م) للطرق المحروقة داخل القطع الكبيرة، حسب fclass
ASSUMED_WIDTH = {
    "motorway": 40, "trunk": 40, "primary": 32, "secondary": 24, "tertiary": 18,
    "motorway_link": 14, "trunk_link": 14, "primary_link": 14,
    "secondary_link": 10, "tertiary_link": 10,
    "residential": 10, "unclassified": 10,
    "service": 6, "living_street": 6, "track": 6,
}
MAJOR_FCLASS = {"motorway", "trunk", "primary", "secondary", "tertiary",
                "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
MAJOR_BUFFER_M = 15
MAJOR_P10, MAJOR_LEN, MAJOR_MED_MAX = 24, 150, 70   # شروط الطريق الرئيسي المقاس
END_TRIM_M = 6       # استبعاد 6 م عند طرفي المقطع لحساب p10
SPUR_EXTRA = 4       # تقليم الفروع: EDT التقاطع + 4
ISOLATED_MIN = 15    # الفرع المعزول الأقصر من 15 م ينحذف
BUS_NET_MIN_ROW = 8  # شبكة المشي/الشوارع الكاملة: المقاطع p10 ≥ 8

# ───────────── المركبات ─────────────
# كل القيم تقديرية للمتوسط والفان وتحتاج معايرة ميدانية
VEHICLES = {
    "large": dict(suffix="L", name="باص كبير", seats=72, length=12.0, width=2.70,
                  min_row=8, sharp_sum=24, vsharp_sum=20, turn_room=10, turnaround=11,
                  pen=(16, 12, 10), score_w=(16, 13, 10), narrow=14),
    "medium": dict(suffix="M", name="باص متوسط", seats=26, length=7.2, width=2.05,
                   min_row=6, sharp_sum=17, vsharp_sum=14, turn_room=7, turnaround=7.5,
                   pen=(12, 10, 8), score_w=(12, 10, 8), narrow=10),
    "small": dict(suffix="S", name="فان", seats=14, length=5.4, width=1.90,
                  min_row=5, sharp_sum=13, vsharp_sum=11, turn_room=5.5, turnaround=6,
                  pen=(10, 8, 6), score_w=(10, 8, 6), narrow=8),
}
VEH_ORDER = ["large", "medium", "small"]     # من الأكبر للأصغر
PEN_FACTORS = (1.0, 1.4, 2.0, 3.0)
TURN_SHARP_DEG, TURN_VSHARP_DEG = 60, 120
TURN_DIR_M = 15      # طول المقطع المستخدم لحساب الاتجاه

# ───────────── التصنيف ─────────────
WALK_FREE_M = 30     # أول 30 م مشي مجاني من البيت للشارع
YOUNG_FACTOR = 1.4   # معامل المشي للابتدائي والطفولة المبكرة
HARD_WALK_M = 250    # مشي أكبر من كذا = صعب مباشرة
WALK_STEPS = [(30, 0), (80, 1), (150, 3), (250, 5)]  # (حد المشي, نقاط) وما فوق = 7
WALK_TOP_PTS = 7
REVERSE_STEPS = [(30, 1), (80, 2)]; REVERSE_TOP = 3
NARROW_LEN_STEPS = [(300, 1), (700, 2)]
TURN_PTS_CAP = 3
LEVEL_CUTS = (3, 6)  # 0-2 سهل، 3-5 متوسط، 6+ صعب
ZONE_PTS = {"سكني عشوائي": 2}
ZONE_PTS_CONTAINS = {"التاريخية": 2}
ZONE_PTS_1 = ["المنطقة المركزية", "الخدمات التجارية", "المستودعات", "الورش",
              "الصناعات الخفيفة", "المدن الصناعية", "معارض السيارات"]
CONF_LOW_SNAP, CONF_MID_SNAP = 150, 60
PICKUP_MIN_WALK = 50  # نقاط التجميع للي مشيهم أكثر من 50 م
PICKUP_CLUSTER_M = 60

# ───────────── الشبكة المتصلة (الإصدار 3) ─────────────
NET_SNAP_M = 3
NET_BRIDGE_M = 15
OSM_LINK_M = 15
PEAK_FACTOR = 0.75   # معامل الذروة على السرعات
SPEED_BY_WIDTH = [(30, 50), (20, 40), (14, 30), (10, 20)]  # (وسيط العرض ≥, كم/س)
SPEED_NARROW = 12
SPEED_MAJOR_MEASURED = 45
SPEED_OSM = {"motorway": 70, "trunk": 60, "primary": 50, "secondary": 40, "tertiary": 35,
             "motorway_link": 35, "trunk_link": 30, "primary_link": 30,
             "secondary_link": 25, "tertiary_link": 25}

# ───────────── المسارات (VRP) ─────────────
SCHOOL_ARRIVAL = "06:45"
MAX_RIDE_MIN = 75        # الحد المرن لزمن الرحلة (د)
HARD_RIDE_FACTOR = 1.6   # الحد الصارم = 1.6 × المرن
LATE_PENALTY = 10        # عقوبة لكل ثانية زيادة عن الحد المرن
LOAD_FACTOR = 0.9        # السعة = المقاعد × 0.9
STOP_MERGE_M = 40
STOP_SERVICE_S = 45
STUDENT_SERVICE_S = 10
FIXED_COST = 14400
VEH_COST_FACTOR = {"large": 1.0, "medium": 0.8, "small": 0.65}
DROP_PENALTY = 10_000_000
VRP_STRATEGIES = ["PATH_CHEAPEST_ARC", "SAVINGS", "LOCAL_CHEAPEST_INSERTION"]
VRP_TIME_MIN, VRP_TIME_MAX = 6, 90   # ثواني لكل مدرسة
MATRIX_BATCH = 60

# ───────────── المؤشرات التشغيلية ─────────────
TRIPS_PER_DAY = 2
SCHOOL_DAYS = 180
FUEL_L_PER_100KM = {"large": 30, "medium": 18, "small": 12}
FUEL_PRICE_SAR = 1.66
CO2_KG_PER_L = 2.68
SCENARIO_LIMITS = [60, 75, 90, 120]
SCENARIO_SEARCH_SCALE = 0.35

# ───────────── أخرى ─────────────
WORKERS = 2
EDITABLE = ["SCHOOL_ARRIVAL", "MAX_RIDE_MIN", "PEAK_FACTOR", "LOAD_FACTOR", "STOP_MERGE_M",
            "TRIPS_PER_DAY", "SCHOOL_DAYS", "FUEL_PRICE_SAR", "HARD_WALK_M", "WALK_FREE_M",
            "YOUNG_FACTOR"]


def _apply_settings():
    """قراءة settings.json اللي تكتبه اللوحة وتطبيقه على المتغيرات المسموحة."""
    if not SETTINGS_JSON.exists():
        return
    try:
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return
    g = globals()
    for k in EDITABLE:
        if k in s and type(s[k]) in (int, float, str):
            g[k] = type(g[k])(s[k])


_apply_settings()
