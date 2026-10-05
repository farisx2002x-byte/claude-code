"""صفحة البيانات: رفع المدخلات وفحصها، المدينة التجريبية، وقوالب الملفات."""

import pandas as pd
import streamlit as st

from transport_hub.core import data as D
from transport_hub.core import demo_city, geo, safety
from transport_hub.core.access import load_access
from transport_hub.ops import fleetmgmt as F
from transport_hub.ops import performance as P
from transport_hub.transit import gtfs
from transport_hub.ui import common as U

TEMPLATES = {
    "السكان": pd.DataFrame(
        {
            "zone_id": ["Z1"],
            "name": ["منطقة 1"],
            "district": ["حي 1"],
            "pop": [5000],
            "jobs": [800],
            "students": [900],
            "low_income": [0.3],
            "lon": [39.17],
            "lat": [21.54],
        }
    ),
    "نقاط الجذب": pd.DataFrame({"name": ["مستشفى 1"], "category": ["مستشفى"], "lon": [39.18], "lat": [21.55], "weight": [8]}),
    "رحلات التاكسي": pd.DataFrame(
        {
            "pickup_time": ["2025-03-02 08:15"],
            "pickup_lon": [39.17],
            "pickup_lat": [21.54],
            "dropoff_lon": [39.19],
            "dropoff_lat": [21.56],
            "fare": [22.5],
            "distance_km": [7.2],
            "duration_min": [18],
            "vehicle_id": [12],
            "wait_min": [5],
        }
    ),
    "مواقف التاكسي": pd.DataFrame({"name": ["موقف 1"], "lon": [39.17], "lat": [21.54]}),
    "تتبع المركبات AVL": pd.DataFrame(
        {
            "date": ["2025-03-02"],
            "route_id": ["R1"],
            "trip_id": ["R1_0_21600"],
            "stop_id": ["S_R1_0"],
            "scheduled": ["06:00:30"],
            "actual": ["06:02:10"],
        }
    ),
    "ركاب APC": pd.DataFrame(
        {"date": ["2025-03-02"], "route_id": ["R1"], "trip_id": ["R1_0_21600"], "stop_id": ["S_R1_0"], "boardings": [12], "alightings": [0]}
    ),
    "منحنى الازدحام": pd.DataFrame({"hour": [7, 8, 13, 17], "factor": [1.6, 1.8, 1.1, 1.7]}),
    "سجل الأسطول": pd.DataFrame(
        {
            "vehicle_id": [1],
            "type": ["باص كبير"],
            "seats": [72],
            "year": [2020],
            "odometer_km": [180000],
            "last_service_km": [172000],
            "last_service_date": ["2025-01-15"],
        }
    ),
}


DATASET_LABELS = {
    "roads_lines": "شوارع OSM",
    "congestion": "الازدحام",
    "population": "السكان",
    "poi": "نقاط الجذب",
    "gtfs": "النقل العام (GTFS)",
    "trips": "رحلات التاكسي",
    "stands": "مواقف التاكسي",
    "avl": "تتبع AVL",
    "apc": "ركاب APC",
    "register": "سجل الأسطول",
}


def _store(name, df, source="upload", obj=False):
    """يحفظ مجموعة بيانات ويسجل مصدرها (تجريبي/مرفوع) وتقرير الصفوف المستبعدة، ويرفع رسالة للمستخدم."""
    w = U.ws()
    (w.save_obj if obj else w.save_df)(name, df)
    w.set_source(name, source)
    if not obj and df.attrs.get("issues") is not None:
        rep = w.obj("load_report") or {}
        rep[name] = dict(rows_in=df.attrs.get("rows_in"), rows_out=df.attrs.get("rows_out"), issues=df.attrs["issues"])
        w.save_obj("load_report", rep)
        bad = {k: v for k, v in df.attrs["issues"].items() if v}
        if bad:
            st.session_state["hub_flash"] = f"تم تحميل {name}: " + "، ".join(f"{k}: {v}" for k, v in bad.items())
    w.log("dataset_loaded", name=name, source=source, rows=(len(df) if not obj else None))


def _read_csv(up):
    safety.check_size(up.size)
    return safety.check_csv_rows(pd.read_csv(up, encoding="utf-8-sig"))


def _set_proj(pop_df):
    w = U.ws()
    w.save_obj("proj_epsg", geo.Projector.for_points(pop_df["lon"], pop_df["lat"]).epsg)


def load_demo():
    w = U.ws()
    d = demo_city.build_all()
    p = geo.Projector.for_points(d["population"].lon, d["population"].lat)
    w.save_obj("proj_epsg", p.epsg)
    _store("population", D.clean_population(d["population"], p), "demo")
    _store("poi", D.clean_poi(d["poi"], p), "demo")
    _store("gtfs", d["gtfs"], "demo", obj=True)
    _store("trips", D.clean_trips(d["trips"], p), "demo")
    _store("stands", p.attach(d["stands"]), "demo")
    avl, apc = demo_city.avl_apc(d["gtfs"])
    _store("avl", avl, "demo")
    _store("apc", apc, "demo")
    _store("register", demo_city.vehicle_register(), "demo")
    _store("roads_lines", demo_city.street_lines(), "demo", obj=True)
    demo_city.learn_demo_congestion(w)
    w.log("demo_loaded")
    st.cache_data.clear()


def _roads_tab(w):
    from transport_hub.core import roadnet

    st.caption(
        "شوارع OSM تستبدل التقدير (مستقيم × 1.3) بمسافات المشي والقيادة الفعلية: اتجاه واحد، جسور، حواجز مثل الأنهار والسكك. "
        "الصيغ: GeoJSON، أو zip لـ shapefile من Geofabrik (حقول fclass وoneway وmaxspeed)، أو GPKG. الملفات الكبيرة تُقصّ تلقائياً لمنطقة السكان."
    )
    pop = U.get("population")
    bbox = None
    if pop is not None:
        m = 0.03
        bbox = (float(pop["lon"].min() - m), float(pop["lat"].min() - m), float(pop["lon"].max() + m), float(pop["lat"].max() + m))
    up = st.file_uploader("ملف الشوارع", type=["geojson", "json", "zip", "gpkg"], key="hub_up_roads")
    if up is not None and st.button("اعتمد الشوارع", key="hub_ok_roads"):
        try:
            safety.check_size(up.size)
            lines = roadnet.read_roads(up.getvalue(), up.name, bbox=bbox)
            if bbox:
                lines = lines.clip(bbox)
            if len(lines) == 0:
                raise roadnet.RoadDataError("لا شوارع داخل منطقة السكان: تأكد أن الملف يغطي نفس المدينة")
            _store("roads_lines", lines, obj=True)
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(str(e))
    if bbox and st.button("تنزيل الشوارع من OpenStreetMap (Overpass) لمنطقة السكان", key="hub_overpass"):
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        if area > 0.6:
            st.error("المنطقة كبيرة على Overpass؛ حمّل ملف المنطقة من Geofabrik وارفعه أعلاه")
        else:
            try:
                with st.spinner("جاري التنزيل…"):
                    lines = roadnet.fetch_overpass(bbox)
                _store("roads_lines", lines, obj=True)
                st.cache_data.clear()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"تعذر التنزيل ({type(e).__name__}). تحقق من الاتصال، أو ارفع الملف يدوياً.")
    if U.has_roads():
        U.section("حالة شبكة الشوارع")
        net = load_access(w, True).net
        s = net.summary()
        linked = 100 * float((net.snap(pop[["x", "y"]].to_numpy(), "walk")[0] >= 0).mean()) if pop is not None else None
        U.kpis(
            [
                (f"{s['km']:,.0f}", "كم شوارع"),
                (f"{s['nodes']:,}", "عقدة"),
                (f"{s['oneway_pct']:.0f}%", "اتجاه واحد"),
                (f"{linked:.0f}%" if linked is not None else "—", "مناطق مرتبطة بالشبكة (≤ 300 م)", "ok" if (linked or 0) >= 95 else "mid"),
            ]
        )
        if linked is not None and linked < 95:
            st.warning("جزء من المناطق بعيد عن الشوارع المحمّلة (يُقدَّر بالخط المستقيم). تأكد أن الملف يغطي كل المدينة.")
        if st.button("إزالة الشوارع (الرجوع للتقدير)", key="hub_rm_roads"):
            w.delete("roads_lines")
            st.cache_data.clear()
            st.rerun()
    else:
        U.empty("لا شوارع محمّلة بعد: المسافات الآن تقدير (مستقيم × 1.3).")


def render():
    U.style()
    U.page_header(
        "البيانات",
        "ارفع مدخلات المنصة أو حمّل مدينة تجريبية، وراجع جودتها.",
        "كل البيانات تبقى على جهازك في مجلد workspace. القوالب في تبويب «قوالب». الصفوف المرفوضة (إحداثيات خاطئة، قيم فارغة) تُسجَّل في «فحص الجودة».",
    )
    st.caption("ارفع بياناتك، أو حمّل المدينة التجريبية لمعاينة كل وحدات المنصة. كل البيانات تبقى على جهازك داخل مجلد workspace.")
    w = U.ws()
    flash = st.session_state.pop("hub_flash", None)
    if flash:
        st.warning(flash)
    c1, c2 = st.columns(2)
    if c1.button("تحميل مدينة تجريبية (8×8 كم)", type="primary", key="hub_demo"):
        load_demo()
        st.rerun()
    if c2.button("مسح كل البيانات", key="hub_clear"):
        w.clear()
        st.cache_data.clear()
        st.rerun()

    tabs = st.tabs(["السكان", "نقاط الجذب", "النقل العام (GTFS)", "التاكسي", "التشغيل", "الشوارع (OSM)", "قوالب", "فحص الجودة"])
    with tabs[0]:
        st.caption("الأعمدة المطلوبة: zone_id, pop, lon, lat. اختيارية: name, district, jobs, students, low_income.")
        up = st.file_uploader("ملف السكان (CSV)", type="csv", key="hub_up_pop")
        if up is not None and st.button("اعتمد السكان", key="hub_ok_pop"):
            try:
                raw = _read_csv(up)
                p = geo.Projector.for_points(raw["lon"], raw["lat"])
                w.save_obj("proj_epsg", p.epsg)
                _store("population", D.clean_population(raw, p))
                st.success(f"تم: {len(raw)} منطقة")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))
    with tabs[1]:
        st.caption("الأعمدة: name, category, lon, lat (+ weight اختياري). الفئات المعروفة لها أوزان جذب افتراضية.")
        up = st.file_uploader("ملف نقاط الجذب (CSV)", type="csv", key="hub_up_poi")
        if up is not None and st.button("اعتمد نقاط الجذب", key="hub_ok_poi"):
            p = U.proj()
            if p is None:
                st.error("ارفع ملف السكان أولاً (يحدد الإسقاط)")
            else:
                try:
                    _store("poi", D.clean_poi(_read_csv(up), p))
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    with tabs[2]:
        st.caption("ملف zip بصيغة GTFS (stops, routes, trips, stop_times، وcalendar اختياري).")
        up = st.file_uploader("GTFS (zip)", type="zip", key="hub_up_gtfs")
        if up is not None and st.button("اعتمد GTFS", key="hub_ok_gtfs"):
            try:
                safety.check_size(up.size)
                safety.check_zip(up.getvalue())
                feed = gtfs.read_zip(up.getvalue())
                _store("gtfs", {k: v for k, v in feed.tables().items()}, obj=True)
                if U.proj() is None:
                    w.save_obj("proj_epsg", geo.Projector.for_points(feed.stops["stop_lon"].dropna(), feed.stops["stop_lat"].dropna()).epsg)
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))
    with tabs[3]:
        st.caption("رحلات: pickup_time, pickup_lon, pickup_lat (+ dropoff_lon/lat, fare, distance_km, duration_min, vehicle_id, wait_min).")
        up = st.file_uploader("رحلات التاكسي (CSV)", type="csv", key="hub_up_trips")
        if up is not None and st.button("اعتمد الرحلات", key="hub_ok_trips"):
            p = U.proj()
            if p is None:
                st.error("ارفع ملف السكان أو GTFS أولاً (يحدد الإسقاط)")
            else:
                try:
                    _store("trips", D.clean_trips(_read_csv(up), p))
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        up2 = st.file_uploader("مواقف التاكسي الحالية (CSV: name, lon, lat)", type="csv", key="hub_up_stands")
        if up2 is not None and st.button("اعتمد المواقف", key="hub_ok_stands") and U.proj() is not None:
            _store("stands", U.proj().attach(_read_csv(up2)))
            st.cache_data.clear()
            st.rerun()
    with tabs[4]:
        st.caption("بيانات التشغيل الفعلية: تتبع المركبات AVL، عدّادات الركاب APC، وسجل الأسطول. كلها اختيارية وتفعّل صفحات الأداء الفعلي والتشغيل.")
        for key, label, cols, fn in (
            ("avl", "تتبع المركبات AVL (CSV)", "date, route_id, trip_id, stop_id, scheduled, actual", P.clean_avl),
            ("apc", "عدّادات الركاب APC (CSV)", "date, route_id, trip_id, stop_id, boardings, alightings", P.clean_apc),
            ("register", "سجل الأسطول (CSV)", "vehicle_id, type, seats, year, odometer_km, last_service_km, last_service_date", F.clean_register),
        ):
            st.caption(f"{label}: {cols}")
            up = st.file_uploader(label, type="csv", key=f"hub_up_{key}")
            if up is not None and st.button(f"اعتمد: {label}", key=f"hub_ok_{key}"):
                try:
                    raw = _read_csv(up)
                    fn(raw)  # فحص الأعمدة
                    _store(key, raw)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    with tabs[5]:
        _roads_tab(w)
    with tabs[6]:
        for name, df in TEMPLATES.items():
            U.download_df(f"قالب: {name}", df, f"template_{name}.csv", f"hub_tpl_{name}")
    with tabs[7]:
        feed = U.feed_obj()
        rep = D.quality_report(U.get("population"), U.get("poi"), U.get("trips"), gtfs.validate(feed) if feed else None, w.obj("load_report"))
        if rep.empty:
            U.empty("ما فيه بيانات محمّلة بعد.")
        else:
            U.table(rep)
        src = w.sources()
        sets = [
            {
                "المجموعة": DATASET_LABELS.get(k, k),
                "المصدر": {"demo": "تجريبي", "upload": "مرفوع"}.get(src.get(k), "—"),
                "آخر تحديث": v.replace("T", " "),
            }
            for k, v in w.meta().items()
            if not k.startswith("_") and k not in ("proj_epsg", "load_report", "scenarios")
        ]
        if sets:
            U.section("مجموعات البيانات المحمّلة")
            U.table(pd.DataFrame(sets))
