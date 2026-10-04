"""صفحة البيانات: رفع المدخلات وفحصها، المدينة التجريبية، وقوالب الملفات."""
import io

import numpy as np
import pandas as pd
import streamlit as st

from transport_hub.core import data as D
from transport_hub.core import demo_city, geo
from transport_hub.transit import gtfs
from transport_hub.ui import common as U

TEMPLATES = {
    "السكان": pd.DataFrame({"zone_id": ["Z1"], "name": ["منطقة 1"], "district": ["حي 1"], "pop": [5000], "jobs": [800], "students": [900], "low_income": [0.3], "lon": [39.17], "lat": [21.54]}),
    "نقاط الجذب": pd.DataFrame({"name": ["مستشفى 1"], "category": ["مستشفى"], "lon": [39.18], "lat": [21.55], "weight": [8]}),
    "رحلات التاكسي": pd.DataFrame({"pickup_time": ["2025-03-02 08:15"], "pickup_lon": [39.17], "pickup_lat": [21.54], "dropoff_lon": [39.19], "dropoff_lat": [21.56],
                                   "fare": [22.5], "distance_km": [7.2], "duration_min": [18], "vehicle_id": [12], "wait_min": [5]}),
    "مواقف التاكسي": pd.DataFrame({"name": ["موقف 1"], "lon": [39.17], "lat": [21.54]}),
}


def _read_csv(up):
    return pd.read_csv(up, encoding="utf-8-sig")


def _set_proj(pop_df):
    w = U.ws()
    w.save_obj("proj_epsg", geo.Projector.for_points(pop_df["lon"], pop_df["lat"]).epsg)


def load_demo():
    w = U.ws()
    d = demo_city.build_all()
    p = geo.Projector.for_points(d["population"].lon, d["population"].lat)
    w.save_obj("proj_epsg", p.epsg)
    w.save_df("population", D.clean_population(d["population"], p))
    w.save_df("poi", D.clean_poi(d["poi"], p))
    w.save_obj("gtfs", d["gtfs"])
    w.save_df("trips", D.clean_trips(d["trips"], p))
    w.save_df("stands", p.attach(d["stands"]))
    w.log("demo_loaded")
    st.cache_data.clear()


def render():
    U.style()
    st.markdown("### البيانات")
    st.caption("ارفع بياناتك، أو حمّل المدينة التجريبية لمعاينة كل وحدات المنصة. كل البيانات تبقى على جهازك داخل مجلد workspace.")
    w = U.ws()
    c1, c2 = st.columns(2)
    if c1.button("تحميل مدينة تجريبية (8×8 كم)", type="primary", key="hub_demo"):
        load_demo()
        st.rerun()
    if c2.button("مسح كل البيانات", key="hub_clear"):
        w.clear()
        st.cache_data.clear()
        st.rerun()

    tabs = st.tabs(["السكان", "نقاط الجذب", "النقل العام (GTFS)", "التاكسي", "قوالب", "فحص الجودة"])
    with tabs[0]:
        st.caption("الأعمدة المطلوبة: zone_id, pop, lon, lat. اختيارية: name, district, jobs, students, low_income.")
        up = st.file_uploader("ملف السكان (CSV)", type="csv", key="hub_up_pop")
        if up is not None and st.button("اعتمد السكان", key="hub_ok_pop"):
            try:
                raw = _read_csv(up)
                p = geo.Projector.for_points(raw["lon"], raw["lat"])
                w.save_obj("proj_epsg", p.epsg)
                w.save_df("population", D.clean_population(raw, p))
                st.success(f"تم: {len(raw)} منطقة")
                st.cache_data.clear(); st.rerun()
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
                    w.save_df("poi", D.clean_poi(_read_csv(up), p)); st.cache_data.clear(); st.rerun()
                except Exception as e:
                    st.error(str(e))
    with tabs[2]:
        st.caption("ملف zip بصيغة GTFS (stops, routes, trips, stop_times، وcalendar اختياري).")
        up = st.file_uploader("GTFS (zip)", type="zip", key="hub_up_gtfs")
        if up is not None and st.button("اعتمد GTFS", key="hub_ok_gtfs"):
            try:
                feed = gtfs.read_zip(up.getvalue())
                w.save_obj("gtfs", {k: v for k, v in feed.tables().items()})
                if U.proj() is None:
                    w.save_obj("proj_epsg", geo.Projector.for_points(feed.stops["stop_lon"].dropna(), feed.stops["stop_lat"].dropna()).epsg)
                st.cache_data.clear(); st.rerun()
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
                    w.save_df("trips", D.clean_trips(_read_csv(up), p)); st.cache_data.clear(); st.rerun()
                except Exception as e:
                    st.error(str(e))
        up2 = st.file_uploader("مواقف التاكسي الحالية (CSV: name, lon, lat)", type="csv", key="hub_up_stands")
        if up2 is not None and st.button("اعتمد المواقف", key="hub_ok_stands") and U.proj() is not None:
            w.save_df("stands", U.proj().attach(_read_csv(up2))); st.cache_data.clear(); st.rerun()
    with tabs[4]:
        for name, df in TEMPLATES.items():
            U.download_df(f"قالب: {name}", df, f"template_{name}.csv", f"hub_tpl_{name}")
    with tabs[5]:
        feed = U.feed_obj()
        rep = D.quality_report(U.get("population"), U.get("poi"), U.get("trips"), gtfs.validate(feed) if feed else None)
        if rep.empty:
            U.empty("ما فيه بيانات محمّلة بعد.")
        else:
            U.table(rep)
        st.json({k: v for k, v in w.meta().items() if not k.startswith("_")})
