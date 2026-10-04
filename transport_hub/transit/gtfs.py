"""قراءة GTFS (zip) وفحصه وكتابته. الحد الأدنى: stops, routes, trips, stop_times (+calendar اختياري)."""
import io
import zipfile
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REQUIRED = ["stops", "routes", "trips", "stop_times"]


@dataclass
class Feed:
    stops: pd.DataFrame
    routes: pd.DataFrame
    trips: pd.DataFrame
    stop_times: pd.DataFrame
    calendar: pd.DataFrame = field(default_factory=pd.DataFrame)

    def tables(self):
        return dict(stops=self.stops, routes=self.routes, trips=self.trips, stop_times=self.stop_times, calendar=self.calendar)


def parse_time(s):
    """HH:MM:SS (يقبل أكثر من 24 ساعة كما في GTFS) → ثواني. القيم الفاضية → NaN."""
    s = pd.Series(s).astype("string")
    parts = s.str.split(":", expand=True)
    if parts.shape[1] < 3:
        return pd.Series(np.nan, index=s.index)
    h, m, sec = (pd.to_numeric(parts[i], errors="coerce") for i in range(3))
    return (h * 3600 + m * 60 + sec).astype(float)


def from_tables(t):
    miss = [k for k in REQUIRED if k not in t or t[k] is None or len(t[k]) == 0]
    if miss:
        raise ValueError(f"GTFS ناقص: الملفات {miss} مطلوبة")
    st = t["stop_times"].copy()
    st["arr"] = parse_time(st["arrival_time"])
    st["dep"] = parse_time(st["departure_time"])
    st["arr"] = st["arr"].fillna(st["dep"])
    st["dep"] = st["dep"].fillna(st["arr"])
    st["stop_sequence"] = pd.to_numeric(st["stop_sequence"])
    st = st.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)
    stops = t["stops"].copy()
    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    routes = t["routes"].copy()
    if "route_short_name" not in routes:
        routes["route_short_name"] = routes["route_id"]
    if "route_long_name" not in routes:
        routes["route_long_name"] = routes["route_short_name"]
    trips = t["trips"].copy()
    if "direction_id" not in trips:
        trips["direction_id"] = 0
    return Feed(stops, routes, trips, st, t.get("calendar", pd.DataFrame()) if t.get("calendar") is not None else pd.DataFrame())


def read_zip(path_or_bytes):
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    t = {}
    with zipfile.ZipFile(src) as z:
        names = {n.split("/")[-1][:-4]: n for n in z.namelist() if n.endswith(".txt")}
        for k in REQUIRED + ["calendar", "frequencies"]:
            if k in names:
                t[k] = pd.read_csv(z.open(names[k]), dtype=str, encoding="utf-8-sig")
    return from_tables(t)


def write_zip(tables, path):
    """يكتب جداول GTFS (dict من DataFrame) في zip."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for k, df in tables.items():
            if df is None or len(df) == 0:
                continue
            cols = [c for c in df.columns if c not in ("arr", "dep")]
            z.writestr(f"{k}.txt", df[cols].to_csv(index=False))


def validate(feed):
    """فحوصات جودة GTFS: العدد والأهمية."""
    r = []
    stops, trips, st, routes = feed.stops, feed.trips, feed.stop_times, feed.routes
    r.append(("محطات بدون إحداثيات", int(stops[["stop_lat", "stop_lon"]].isna().any(axis=1).sum()), "عالية"))
    r.append(("محطات مكررة (نفس المعرّف)", int(stops["stop_id"].duplicated().sum()), "عالية"))
    r.append(("stop_times تشير لمحطة غير موجودة", int((~st["stop_id"].isin(stops["stop_id"])).sum()), "عالية"))
    r.append(("رحلات تشير لخط غير موجود", int((~trips["route_id"].isin(routes["route_id"])).sum()), "عالية"))
    r.append(("رحلات بدون أوقات", int((~trips["trip_id"].isin(st["trip_id"])).sum()), "متوسطة"))
    r.append(("محطات غير مستخدمة", int((~stops["stop_id"].isin(st["stop_id"])).sum()), "منخفضة"))
    g = st.groupby("trip_id")
    back = (g["arr"].diff() < 0).sum()
    r.append(("أوقات تتراجع داخل الرحلة", int(back), "عالية"))
    r.append(("رحلات بمحطة واحدة فقط", int((g.size() < 2).sum()), "متوسطة"))
    return pd.DataFrame(r, columns=["الفحص", "العدد", "الأهمية"])


def active_trips(feed, weekday=None):
    """رحلات يوم معين (0=الاثنين) حسب calendar؛ لو ما فيه calendar كل الرحلات."""
    cal = feed.calendar
    if cal is None or len(cal) == 0 or weekday is None:
        return feed.trips
    day = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][weekday]
    ok = cal.loc[cal[day].astype(str) == "1", "service_id"]
    return feed.trips[feed.trips["service_id"].isin(ok)]
