"""قراءة الطلاب والمدارس والقطع والطرق وحفظها في work/ (parquet)."""
import difflib
import html
import re
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

import config as C

_to_utm = Transformer.from_crs("EPSG:4326", C.CRS_UTM, always_xy=True)

# تصحيحات ربط أسماء المدارس: اسم الطالب ← (الاسم الرسمي, match)
MANUAL_LOOKUP = {
    "جيل القرآن الأهلية لتحفيظ القرآن الكريم": ("جيل القرآن الأهلية", "manual"),
    "جيل الجزيرة - الابتدائي والمتوسط": ("جيل الجزيرة الأهلية", "manual"),
    "جيل الجزيرة الثانوية": ("جيل الجزيرة الأهلية", "confirm"),
    "الشروق العلمية": ("ابتدائية الشروق العلمية الأهلية وملحق متوسطة", "manual"),
    "البنان الأهلية": ("البنان الخاصة", "confirm"),
    "ياسمين جدة": ("ياسمين جدة النموذجية", "manual"),
    "السروات السلمانية": ("السروات الثانوية الأهلية - مسارات - السليمانية", "manual"),
    "مدارس الشورى الاهلية": ("مدارس الشورى الأهلية للبنات", "confirm"),
    "مدرسة الأخاء بنات": ("مدرسة الأخاء بنات", "manual"),
    "الفيصلية الاهلية": ("مدارس الفيصلية", "manual"),
    "الفلك المنير": ("الفلك المنير", "nolocation"),
    "النصر الاهلية فرع الفروسية": ("", "none"),
}
FLEET_ALIAS_DEFAULT = {
    "مدارس الفيصلية ( الرحاب )": "مدارس الفيصلية",
    "مدارس الشورى الأهلية بنين": "مدارس الشورى الأهلية للبنين",
    "مدارس الشورى الأهلية": "مدارس الشورى الأهلية للبنات",
}


def norm_stage(s):
    """توحيد المرحلة: ابتدائي / متوسط / ثانوي / طفولة مبكرة / غير معروف."""
    s = (s or "").strip()
    if "طفولة" in s:
        return "طفولة مبكرة"
    if "ثانو" in s:
        return "ثانوي"
    if "متوسط" in s:
        return "متوسط"
    if "ابتدائ" in s or "اولية" in s or "أولية" in s or "الاولية" in s:
        return "ابتدائي"
    return "غير معروف"


def norm_name(s):
    s = re.sub(r"[ً-ْـ]", "", str(s))
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", s).strip()


_PM = re.compile(r"<Placemark\b.*?</Placemark>", re.S)
_NAME = re.compile(r"<name>(.*?)</name>", re.S)
_DESC = re.compile(r"<description>(.*?)</description>", re.S)
_COORD = re.compile(r"<coordinates>\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)")
FIELDS = {"sid": "رقم الطالب", "school": "المدرسة", "stage": "المرحلة", "guardian": "ولي الأمر",
          "phone": "الجوال", "address": "العنوان"}


def _text(d):
    d = re.sub(r"<!\[CDATA\[|\]\]>", "", d)
    d = re.sub(r"(?i)<br\s*/?>|</tr>|</p>|</div>|</li>", "\n", d)
    d = re.sub(r"(?i)</t[dh]>", " | ", d)
    d = re.sub(r"<[^>]+>", " ", d)
    return html.unescape(d)


def parse_description(d):
    """يقرأ الحقول من وصف HTML: إما «العنوان: قيمة» أو جدول «العنوان | قيمة»."""
    t = _text(d)
    out = {}
    for key, label in FIELDS.items():
        m = re.search(label + r"\s*[:：|]\s*([^\n|]*)", t)
        out[key] = m.group(1).strip() if m else ""
    return out


def parse_students_kml(text):
    rows = []
    for pm in _PM.findall(text):
        nm = _NAME.search(pm)
        co = _COORD.search(pm)
        if not co:
            continue
        d = parse_description((_DESC.search(pm) or [None, ""])[1] if _DESC.search(pm) else "")
        rows.append(dict(name=html.unescape(nm.group(1)).strip() if nm else "", lon=float(co.group(1)),
                         lat=float(co.group(2)), **d))
    df = pd.DataFrame(rows)
    if len(df):
        df["stage"] = df["stage"].map(norm_stage)
        x, y = _to_utm.transform(df["lon"].values, df["lat"].values)
        df["x"], df["y"] = x, y
        df.insert(0, "idx", np.arange(len(df)))
    return df


def read_students(path=None):
    path = path or C.STUDENTS_KML
    return parse_students_kml(open(path, encoding="utf-8", errors="ignore").read())


def read_schools(path=None):
    path = path or C.SCHOOLS_ZIP
    rows = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if not n.lower().endswith(".kml"):
                continue
            t = z.read(n).decode("utf-8", errors="ignore")
            nm = _NAME.findall(t)
            co = _COORD.search(t)
            if not co:
                continue
            # أول <name> غالباً اسم الملف/المجلد؛ نستخدم اسم الـ Placemark لو موجود
            pm = _PM.search(t)
            name = _NAME.search(pm.group(0)).group(1) if pm and _NAME.search(pm.group(0)) else nm[0]
            rows.append(dict(name=html.unescape(name).strip(), lon=float(co.group(1)), lat=float(co.group(2))))
    df = pd.DataFrame(rows)
    x, y = _to_utm.transform(df["lon"].values, df["lat"].values)
    df["x"], df["y"] = x, y
    return df


def build_school_lookup(student_schools, official_names):
    """ربط تلقائي بالتشابه + التصحيحات اليدوية → school_lookup.csv."""
    norm_off = {norm_name(o): o for o in official_names}
    rows = []
    for s in sorted(set(student_schools)):
        if s in MANUAL_LOOKUP:
            off, mt = MANUAL_LOOKUP[s]
        else:
            ns = norm_name(s)
            if ns in norm_off:
                off, mt = norm_off[ns], "exact"
            else:
                hit = difflib.get_close_matches(ns, list(norm_off), n=1, cutoff=0.6)
                off, mt = (norm_off[hit[0]], "auto") if hit else ("", "none")
        rows.append(dict(student_school=s, official_name=off, match=mt))
    return pd.DataFrame(rows)


def load_lookup():
    if C.SCHOOL_LOOKUP.exists():
        return pd.read_csv(C.SCHOOL_LOOKUP, encoding="utf-8-sig").fillna("")
    return None


def load_fleet_alias():
    a = dict(FLEET_ALIAS_DEFAULT)
    if C.FLEET_ALIAS.exists():
        df = pd.read_csv(C.FLEET_ALIAS, encoding="utf-8-sig").fillna("")
        a.update(dict(zip(df.iloc[:, 0], df.iloc[:, 1])))
    return a


def check_files():
    """الخطوة الأولى: التأكد من وجود الملفات الأساسية. يرجع قائمة بالناقص."""
    need = {"الطلاب (KML)": C.STUDENTS_KML, "الاستعمالات (gpkg)": C.LANDUSE_GPKG, "الطرق (zip)": C.ROADS_ZIP,
            "الأسطول (xlsx)": C.FLEET_XLSX, "مواقع المدارس (zip)": C.SCHOOLS_ZIP}
    return [k for k, v in need.items() if not v.exists()]


def load_all():
    """يقرأ كل شيء ويحفظه في work/. يشترط وجود الملفات الأساسية."""
    missing = check_files()
    if missing:
        raise FileNotFoundError("ملفات ناقصة: " + "، ".join(missing) + f"  (DATA_DIR={C.DATA_DIR})")
    C.WORK.mkdir(exist_ok=True)
    st = read_students()
    sc = read_schools()
    print(f"طلاب: {len(st):,} (المتوقع {C.EXPECTED['students']:,}) | مدارس: {len(sc)} (المتوقع {C.EXPECTED['schools']})")
    lk = load_lookup()
    if lk is None:
        lk = build_school_lookup(st["school"].unique(), sc["name"].tolist())
        C.LOCAL_DATA.mkdir(exist_ok=True)
        lk.to_csv(C.SCHOOL_LOOKUP, index=False, encoding="utf-8-sig")
        print("أنشئ data/school_lookup.csv، راجع صفوف match = confirm/none")
    st.to_parquet(C.WORK / "students.parquet")
    sc.to_parquet(C.WORK / "schools.parquet")

    minx, miny = min(st.x.min(), sc.x.min()) - 3000, min(st.y.min(), sc.y.min()) - 3000
    maxx, maxy = max(st.x.max(), sc.x.max()) + 3000, max(st.y.max(), sc.y.max()) + 3000
    bbox = (minx, miny, maxx, maxy)
    lu = gpd.read_file(C.LANDUSE_GPKG, layer="LandUse_Zones", bbox=bbox)
    lu = lu[["LU_ZONE", "geometry"]]
    lu = lu[~lu.geometry.is_empty & lu.geometry.notna()].to_crs(C.CRS_UTM)
    lu.to_parquet(C.WORK / "parcels.parquet")
    di = gpd.read_file(C.LANDUSE_GPKG, layer="Districts_Official")
    di = di[~di.geometry.is_empty & di.geometry.notna()][["ARNAME", "geometry"]].to_crs(C.CRS_UTM)
    di.to_parquet(C.WORK / "districts.parquet")
    lon0, lat0 = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True).transform(minx, miny)
    lon1, lat1 = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True).transform(maxx, maxy)
    rd = gpd.read_file(f"zip://{C.ROADS_ZIP}!{C.ROADS_INNER}", bbox=(lon0, lat0, lon1, lat1))
    keep = [c for c in ("fclass", "oneway", "name", "ref", "maxspeed", "bridge", "tunnel", "geometry") if c in rd]
    rd = rd[keep].to_crs(C.CRS_UTM)
    rd.to_parquet(C.WORK / "roads.parquet")
    print(f"قطع: {len(lu):,} | أحياء: {len(di)} | طرق: {len(rd):,}")
    return st, sc
