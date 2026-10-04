"""المدخلات: ما المطلوب، وين يُحفظ، وهل هو موجود. الواجهة تعتمد عليها لاستقبال الملفات."""
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

import config as C

SPECS = [
    dict(key="students", label="الطلاب (KML)", rel="all_students.kml", where="data", accept=["kml"],
         expected=C.EXPECTED["students"], unit="طالب",
         hint="Placemark لكل طالب: الاسم، ووصف HTML فيه رقم الطالب والمدرسة والمرحلة. بيانات قُصّر، تبقى على جهازك."),
    dict(key="landuse", label="الاستعمالات (GeoPackage)", rel="Jeddah_LandUse_GIS/Jeddah_LandUse_Zones/Jeddah_LandUse_Zones.gpkg",
         where="data", accept=["gpkg"], expected=None, unit="",
         hint="طبقات أمانة جدة: LandUse_Zones وDistricts_Official (EPSG:32637). ملف كبير (~223 MB)."),
    dict(key="roads", label="الطرق (zip)", rel="السعودية/ksa_roads.zip", where="data", accept=["zip"], expected=None, unit="",
         hint="طرق OSM، وبداخله KSA_Roads/Roads.shp."),
    dict(key="fleet", label="الأسطول (Excel)", rel="المدارس كاملة.xlsx", where="data", accept=["xlsx"], expected=C.EXPECTED["fleet_buses"],
         unit="حافلة", hint="الأعمدة المقروءة: اسم المدرسة، المقاعد، النوع فقط. بيانات السائقين لا تُقرأ."),
    dict(key="schools", label="مواقع المدارس (zip KML)", rel="schools.zip", where="local", accept=["zip"],
         expected=C.EXPECTED["schools"], unit="مدرسة", hint="ملف KML لكل مدرسة (نقطة واحدة)، داخل zip."),
]


def data_dir():
    return C.resolve_data_dir()


def path_of(spec):
    base = C.LOCAL_DATA if spec["where"] == "local" else data_dir()
    return Path(base) / spec["rel"]


def _count(spec, p):
    try:
        if spec["key"] == "students":
            return len(re.findall(rb"<Placemark\b", p.read_bytes()))
        if spec["key"] == "schools":
            with zipfile.ZipFile(p) as z:
                return sum(1 for n in z.namelist() if n.lower().endswith(".kml"))
        if spec["key"] == "fleet":
            import pandas as pd
            d = pd.read_excel(p, usecols=["المقاعد"])
            return int(pd.to_numeric(d["المقاعد"], errors="coerce").notna().sum())
    except Exception:
        return None
    return None


def status():
    """قائمة بحالة كل مدخل: found, size_mb, count, expected, ok (العدد مطابق للمتوقع أو ما فيه عدد متوقع)."""
    out = []
    for s in SPECS:
        p = path_of(s)
        found = p.exists()
        n = _count(s, p) if found else None
        out.append(dict(s, path=p, found=found, size_mb=round(p.stat().st_size / 1e6, 1) if found else 0, count=n,
                        ok=found and (s["expected"] is None or n is None or n == s["expected"])))
    return out


def save_upload(key, fileobj):
    """يحفظ ملف مرفوع (file-like) في مكانه الصحيح. المدخلات الكبيرة تُنسخ بدفعات."""
    spec = next(s for s in SPECS if s["key"] == key)
    if spec["where"] == "data" and not os.environ.get("BUS_DATA_DIR") and not data_dir().exists():
        set_data_dir(C.PROJECT / "inputs")
    dest = path_of(spec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(fileobj, f, 1 << 20)
    return dest


def set_data_dir(path):
    """يحفظ مجلد المدخلات في settings.json (يسري على الفور في الواجهة وعلى التشغيل القادم)."""
    s = C.read_settings()
    s["DATA_DIR"] = str(path)
    C.SETTINGS_JSON.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(path).mkdir(parents=True, exist_ok=True)
