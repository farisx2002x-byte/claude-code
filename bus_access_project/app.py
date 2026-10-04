"""لوحة تحكم Streamlit (محلية): تشغيل الخطوات، الإعدادات، والنتائج.   streamlit run app.py"""
import json
import pickle
import shutil
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import config as C

st.set_page_config(page_title="النقل المدرسي — جدة", layout="wide")
st.markdown("""<style>
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {direction: rtl; text-align: right;}
[data-testid="stDataFrame"], .stPlotlyChart, [data-testid="stVegaLiteChart"] {direction: ltr;}
</style>""", unsafe_allow_html=True)

LV_COL = {"سهل": [46, 158, 79], "متوسط": [224, 168, 0], "صعب": [209, 56, 61]}
VEH_COL = {"large": [21, 101, 192], "medium": [239, 108, 0], "small": [106, 27, 154], "pickup": [120, 120, 120]}


def load(name):
    p = C.WORK / name
    return pickle.loads(p.read_bytes()) if p.exists() else None


@st.cache_data(show_spinner=False)
def cached(name, mtime):
    return load(name)


def get(name):
    p = C.WORK / name
    return cached(name, p.stat().st_mtime) if p.exists() else None


# ───────────── الشريط الجانبي ─────────────
with st.sidebar:
    st.header("التشغيل")
    step = st.selectbox("الخطوة", ["report", "score", "routes", "scenarios", "export", "tiles", "network", "load", "all"])
    workers = st.number_input("عدد العمليات", 1, 16, C.WORKERS)
    fresh = st.checkbox("إعادة كل المربعات (--fresh)")
    if st.button("تشغيل", type="primary"):
        cmd = [sys.executable, "run.py", step, "--workers", str(workers)] + (["--fresh"] if fresh else [])
        box, buf = st.empty(), []
        proc = subprocess.Popen(cmd, cwd=C.PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        for line in proc.stdout:
            buf.append(line.rstrip())
            box.code("\n".join(buf[-25:]))
        st.success("انتهى") if proc.wait() == 0 else st.error("فشل التشغيل، راجع السجل")
        st.cache_data.clear()

    st.divider()
    up = st.file_uploader("رفع KML طلاب جديد", type="kml")
    if up is not None and st.button("اعتمد الملف"):
        if C.STUDENTS_KML.exists():
            bak = C.STUDENTS_KML.with_suffix(f".{datetime.now():%Y%m%d_%H%M}.kml.bak")
            shutil.copy(C.STUDENTS_KML, bak)
            st.info(f"نسخة احتياطية: {bak.name}")
        C.STUDENTS_KML.write_bytes(up.getvalue())
        st.success("تم. شغّل الخطوة load ثم all")

    st.divider()
    with st.form("settings"):
        st.subheader("الإعدادات")
        vals = {}
        for k in C.EDITABLE:
            v = getattr(C, k)
            vals[k] = (st.text_input(k, v) if isinstance(v, str) else st.number_input(k, value=float(v) if isinstance(v, float) else int(v)))
        if st.form_submit_button("حفظ"):
            (C.SETTINGS_JSON).write_text(json.dumps(vals, ensure_ascii=False, indent=1), encoding="utf-8")
            st.success("تم الحفظ في settings.json (تسري عند التشغيل القادم)")

S = get("res_scored.pkl")
if S is None:
    st.warning("ما فيه نتائج بعد. شغّل `score` من الشريط الجانبي (بعد load وtiles وnetwork).")
    st.stop()
df, pickups, fleet, quality = S["df"], S["pickups"], S["fleet"], S["quality"]
RT = get("routes.pkl")
SC = get("scenarios.pkl")

school = st.selectbox("المدرسة", ["كل المدارس"] + sorted(df["school"].unique()))
d = df if school == "كل المدارس" else df[df["school"] == school]

tabs = st.tabs(["نظرة عامة", "خريطة الطلاب", "المسارات", "الأسطول والتشغيل", "جودة البيانات", "الملفات"])

with tabs[0]:
    c = st.columns(4)
    c[0].metric("الطلاب", f"{len(d):,}")
    for col, lv in zip(c[1:], ("سهل", "متوسط", "صعب")):
        n = int((d["level_L"] == lv).sum())
        col.metric(f"{lv} (باص كبير)", f"{n:,}", f"{100 * n / max(len(d), 1):.0f}%")
    comp = pd.DataFrame({v: d[f"level_{C.VEHICLES[k]['suffix']}"].value_counts() for k, v in
                         ((k, C.VEHICLES[k]["name"]) for k in C.VEH_ORDER)}).reindex(["سهل", "متوسط", "صعب"]).fillna(0)
    st.bar_chart(comp)
    st.bar_chart(d["rec_vehicle_ar"].value_counts())

with tabs[1]:
    mode = st.radio("التلوين", ["مستوى الباص الكبير", "المركبة الموصى بها"], horizontal=True)
    m = d.dropna(subset=["x"]).copy()
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True).transform(m.x.values, m.y.values)
    m["lon"], m["lat"] = lon, lat
    m["color"] = [LV_COL[v] for v in m["level_L"]] if mode.startswith("مستوى") else [VEH_COL[v] for v in m["rec_vehicle"]]
    layer = pdk.Layer("ScatterplotLayer", m[["lon", "lat", "color"]], get_position="[lon, lat]", get_fill_color="color",
                      get_radius=25, pickable=False)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(latitude=float(m.lat.mean()), longitude=float(m.lon.mean()), zoom=10),
                             map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))

with tabs[2]:
    if RT is None or RT["R"].empty:
        st.info("شغّل خطوة routes لتخطيط المسارات.")
    else:
        R, RS, SA = RT["R"], RT["RS"], RT["SA"]
        Rd = R if school == "كل المدارس" else R[R.school == school]
        st.dataframe(Rd.round(1), width="stretch")
        pick = st.selectbox("مسار", Rd["route"].tolist()) if len(Rd) else None
        if pick:
            from pyproj import Transformer
            T = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True)
            g = RT["G"].get(pick)
            layers = []
            if g is not None and len(g) > 1:
                lo, la = T.transform(g[:, 0], g[:, 1])
                layers.append(pdk.Layer("PathLayer", [{"path": list(zip(lo, la))}], get_path="path", get_width=6,
                                        width_min_pixels=3, get_color=[21, 101, 192]))
                view = pdk.ViewState(latitude=float(np.mean(la)), longitude=float(np.mean(lo)), zoom=13)
                st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view,
                                         map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))
            names = df.set_index("idx")["name"]
            stops = RS[RS.route == pick].sort_values("order").copy()
            lo, la = T.transform(stops.x.values, stops.y.values)
            stops["الموقع"] = [f"https://www.google.com/maps?q={b:.6f},{a:.6f}" for a, b in zip(lo, la)]
            sa = SA[SA.route == pick]
            stops["الأسماء"] = [
                "، ".join(names.get(i, "") for i in sa[(sa.board_time == t) & (abs(sa.ride_min - r) < 1e-6)]["idx"])
                for t, r in zip(stops.time, stops.ride_min)]
            st.dataframe(stops[["order", "time", "students", "الأسماء", "الموقع"]],
                         column_config={"الموقع": st.column_config.LinkColumn()}, width="stretch")
        xl = C.OUTPUT / "جداول_السائقين.xlsx"
        if xl.exists():
            st.download_button("تنزيل جداول السائقين (Excel)", xl.read_bytes(), file_name=xl.name)

with tabs[3]:
    st.dataframe(fleet.round(1), width="stretch")
    if RT is not None and not RT["R"].empty:
        from src import ops
        t = ops.totals(RT["R"], len(RT["SA"]))
        st.json(t)
    if SC is not None:
        st.dataframe(SC.round(1), width="stretch")
        st.line_chart(SC.set_index("حد_الرحلة_دقيقة")["مركبات"])

with tabs[4]:
    st.dataframe(quality, width="stretch")
    if RT is not None:
        nr = df[df["idx"].isin(RT["nores"])]
        st.subheader(f"طلاب بدون مسار ({len(nr)})")
        st.dataframe(nr[["name", "school", "district", "rec_vehicle_ar"]], width="stretch")

with tabs[5]:
    st.caption("ملفات داخلية فيها أسماء قُصّر، لا تُنشر.")
    for p in sorted(C.OUTPUT.glob("*")) if C.OUTPUT.exists() else []:
        if p.is_file() and p.suffix in (".xlsx", ".kml", ".html", ".gpkg", ".json", ".txt"):
            st.download_button(p.name, p.read_bytes(), file_name=p.name, key=p.name)
