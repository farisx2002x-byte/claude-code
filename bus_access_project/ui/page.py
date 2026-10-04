"""صفحة النقل المدرسي (Streamlit). تُستخدم مستقلة (app.py) أو كصفحة جانبية داخل تطبيق مضيف:

    from ui.page import render
    render()                       # داخل ملف الصفحة في التطبيق المضيف
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config as C  # noqa: E402
from src import inputs, service  # noqa: E402
from ui import style  # noqa: E402

LV_COL = {"سهل": [46, 158, 79], "متوسط": [224, 168, 0], "صعب": [209, 56, 61]}
VEH_COL = {"large": [21, 101, 192], "medium": [239, 108, 0], "small": [106, 27, 154], "pickup": [120, 120, 120]}
BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"


def _k(name):
    return f"bus_{name}"


def _header(demo):
    badge = '<span class="bus-badge demo">وضع التجربة (بيانات اصطناعية)</span>' if demo else '<span class="bus-badge">البيانات الحقيقية</span>'
    st.markdown(f'<div class="bus-head"><h2>🚌 النقل المدرسي — جدة</h2>{badge}</div>'
                '<p class="bus-sub">تقييم سهولة وصول المركبات المدرسية للطلاب، وتخطيط المسارات والأسطول.</p>', unsafe_allow_html=True)


def _stepper(demo):
    chips = []
    for s in service.pipeline_state(demo):
        when = datetime.fromtimestamp(s["mtime"]).strftime("%m-%d %H:%M") if s["done"] else "لم تُشغَّل"
        chips.append(f'<div class="bus-step {"done" if s["done"] else ""}"><b>{"✅" if s["done"] else "⬜"} {s["title"]}</b><small>{when}</small></div>')
    st.markdown('<div class="bus-steps">' + "".join(chips) + "</div>", unsafe_allow_html=True)


# ───────────────────────── المدخلات ─────────────────────────
def tab_inputs():
    st.markdown("#### مدخلات البيانات")
    st.caption("أضف الملفات هنا (رفع مباشر) أو حدد مجلد فيه الملفات. بيانات الطلاب قُصّر وتبقى على جهازك ولا تُرسل لأي جهة.")
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    new_dir = c1.text_input("مجلد المدخلات", value=str(inputs.data_dir()), key=_k("datadir"))
    if c2.button("حفظ المسار", key=_k("savedir"), width="stretch"):
        inputs.set_data_dir(new_dir)
        st.rerun()
    for s in inputs.status():
        cls = "ok" if s["ok"] else ("warn" if s["found"] else "bad")
        detail = f'{s["size_mb"]} MB' if s["found"] else "غير موجود"
        if s["found"] and s["count"] is not None:
            detail += f' · {s["count"]:,} {s["unit"]}' + (f' (المتوقع {s["expected"]:,})' if s["expected"] and s["count"] != s["expected"] else "")
        st.markdown(f'<div class="bus-in {cls}"><span>{"✅" if s["ok"] else "⚠️" if s["found"] else "❌"}</span>'
                    f'<div class="t"><b>{s["label"]}</b><small>{s["hint"]}</small><small>{detail}</small></div></div>', unsafe_allow_html=True)
        up = st.file_uploader(f'رفع: {s["label"]}', type=s["accept"], key=_k("up_" + s["key"]), label_visibility="collapsed")
        if up is not None and st.button(f'اعتمد «{s["label"]}»', key=_k("ok_" + s["key"])):
            if s["key"] == "students" and s["found"]:
                bak = s["path"].with_suffix(f".{datetime.now():%Y%m%d_%H%M}.kml.bak")
                bak.write_bytes(s["path"].read_bytes())
            inputs.save_upload(s["key"], up)
            st.success("تم الحفظ")
            st.rerun()
    st.markdown('<p class="bus-note">ملف <code>school_lookup.csv</code> (ربط أسماء المدارس) يتولد أول تشغيل لخطوة «قراءة البيانات»؛ راجع الصفوف المعلّمة confirm / none.</p>',
                unsafe_allow_html=True)


# ───────────────────────── التشغيل ─────────────────────────
def tab_run(demo):
    st.markdown("#### التشغيل")
    if demo:
        st.info("وضع التجربة: يولّد حي اصطناعي صغير ويشغّل كل الخطوات عليه (دقيقة تقريباً). ما يلمس بياناتك الحقيقية.")
        if st.button("توليد بيانات تجريبية وتشغيلها", type="primary", key=_k("demo_run")):
            _run("demo", demo=True)
        return
    c = st.columns([2, 1, 1])
    labels = {k: t for k, t, *_ in service.STEPS}
    labels.update(all="الكل (load → routes)", report="تقرير سريع (score + export)", export="تصدير فقط")
    options = [k for k, *_ in service.STEPS] + ["all", "report", "export"]
    step = c[0].selectbox("الخطوة", options, index=options.index("all"), format_func=labels.get, key=_k("step"))
    workers = c[1].number_input("عدد العمليات", 1, 16, C.WORKERS, key=_k("workers"))
    fresh = c[2].checkbox("إعادة كل المربعات", key=_k("fresh"), help="يتجاهل الكاش")
    miss = service.missing_prereq(step if step not in ("report", "export") else "score")
    if miss and step not in ("export",):
        st.warning(miss)
    if st.button("تشغيل", type="primary", disabled=bool(miss and step not in ("export",)), key=_k("run")):
        _run(step, workers=workers, fresh=fresh)
    with st.expander("الإعدادات والافتراضات"):
        with st.form(_k("settings")):
            vals = {}
            cols = st.columns(3)
            s0 = C.read_settings()
            for i, k in enumerate(C.EDITABLE):
                v = s0.get(k, getattr(C, k))
                with cols[i % 3]:
                    vals[k] = (st.text_input(k, v) if isinstance(v, str) else st.number_input(k, value=float(v) if isinstance(v, float) else int(v)))
            if st.form_submit_button("حفظ"):
                s0.update(vals)
                C.SETTINGS_JSON.write_text(__import__("json").dumps(s0, ensure_ascii=False, indent=1), encoding="utf-8")
                st.success("تم الحفظ (تسري عند التشغيل القادم)")


def _run(step, workers=None, fresh=False, demo=False):
    box, buf = st.empty(), []
    with st.status("جاري التشغيل…", expanded=True) as status:
        def on(line):
            buf.append(line)
            box.code("\n".join(buf[-20:]))
        rc = service.run_step(step, workers, fresh, demo, on)
        status.update(label="انتهى" if rc == 0 else "فشل التشغيل، راجع السجل", state="complete" if rc == 0 else "error")
    st.cache_data.clear()
    if rc == 0:
        st.rerun()


# ───────────────────────── النتائج ─────────────────────────
def _empty(msg):
    st.markdown(f'<div class="bus-empty">{msg}</div>', unsafe_allow_html=True)


def _school_filter(df):
    school = st.selectbox("المدرسة", ["كل المدارس"] + sorted(df["school"].unique()), key=_k("school"))
    return school, (df if school == "كل المدارس" else df[df["school"] == school])


def tab_results(R, school, d):
    n = max(len(d), 1)
    lv = d["level_L"].value_counts()
    cards = [(f"{len(d):,}", "الطلاب", "")] + [(f"{int(lv.get(l, 0)):,} · {100 * lv.get(l, 0) / n:.0f}%", f"{l} (باص كبير)", c)
                                               for l, c in (("سهل", "ok"), ("متوسط", "mid"), ("صعب", "hard"))]
    rec = d["rec_vehicle"].value_counts()
    cards += [(f"{int(rec.get('pickup', 0)):,}", "نقطة تجميع / ترتيب خاص", "")]
    st.markdown(style.kpis(cards), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    comp = pd.DataFrame({C.VEHICLES[k]["name"]: d[f"level_{C.VEHICLES[k]['suffix']}"].value_counts() for k in C.VEH_ORDER}
                        ).reindex(["سهل", "متوسط", "صعب"]).fillna(0)
    c1.caption("مستوى السهولة حسب المركبة"); c1.bar_chart(comp)
    c2.caption("المركبة الموصى بها"); c2.bar_chart(d["rec_vehicle_ar"].value_counts())
    import pydeck as pdk
    from pyproj import Transformer
    mode = st.radio("تلوين الخريطة", ["مستوى الباص الكبير", "المركبة الموصى بها"], horizontal=True, key=_k("mapmode"))
    m = d.dropna(subset=["x"]).copy()
    m["lon"], m["lat"] = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True).transform(m.x.values, m.y.values)
    m["color"] = [LV_COL[v] for v in m["level_L"]] if mode.startswith("مستوى") else [VEH_COL[v] for v in m["rec_vehicle"]]
    layer = pdk.Layer("ScatterplotLayer", m[["lon", "lat", "color"]], get_position="[lon, lat]", get_fill_color="color", get_radius=25)
    st.pydeck_chart(pdk.Deck(layers=[layer], map_style=BASEMAP, initial_view_state=pdk.ViewState(
        latitude=float(m.lat.mean()), longitude=float(m.lon.mean()), zoom=10 if school == "كل المدارس" else 13)))


def tab_routes(R, school, df, demo):
    RT = R["routes"]
    if RT is None or RT["R"].empty:
        return _empty("لا توجد مسارات بعد. شغّل خطوة «المسارات والتصدير».")
    import pydeck as pdk
    from pyproj import Transformer
    Rd = RT["R"] if school == "كل المدارس" else RT["R"][RT["R"].school == school]
    st.dataframe(Rd.round(1), width="stretch")
    if not len(Rd):
        return
    pick = st.selectbox("مسار", Rd["route"].tolist(), key=_k("route"))
    T = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True)
    g = RT["G"].get(pick)
    if g is not None and len(g) > 1:
        lo, la = T.transform(g[:, 0], g[:, 1])
        st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("PathLayer", [{"path": list(zip(lo, la))}], get_path="path", width_min_pixels=3, get_color=[21, 101, 192])],
                                 map_style=BASEMAP, initial_view_state=pdk.ViewState(latitude=float(np.mean(la)), longitude=float(np.mean(lo)), zoom=13)))
    names = df.set_index("idx")["name"]
    stops = RT["RS"][RT["RS"].route == pick].sort_values("order").copy()
    lo, la = T.transform(stops.x.values, stops.y.values)
    stops["الموقع"] = [f"https://www.google.com/maps?q={b:.6f},{a:.6f}" for a, b in zip(lo, la)]
    sa = RT["SA"][RT["SA"].route == pick]
    stops["الأسماء"] = ["، ".join(names.get(i, "") for i in sa[(sa.board_time == t) & (abs(sa.ride_min - r) < 1e-6)]["idx"])
                        for t, r in zip(stops.time, stops.ride_min)]
    st.dataframe(stops[["order", "time", "students", "الأسماء", "الموقع"]], column_config={"الموقع": st.column_config.LinkColumn()}, width="stretch")
    xl = service.dirs(demo)[1] / "جداول_السائقين.xlsx"
    if xl.exists():
        st.download_button("تنزيل جداول السائقين (Excel)", xl.read_bytes(), file_name=xl.name, key=_k("dl_drivers"))


def tab_fleet(R):
    from src import ops
    S, RT, SC = R["scored"], R["routes"], R["scenarios"]
    st.dataframe(S["fleet"].round(1), width="stretch")
    if RT is not None and not RT["R"].empty:
        t = ops.totals(RT["R"], len(RT["SA"]))
        st.markdown(style.kpis([(t["routes"], "مركبات مطلوبة", ""), (f'{t["km_day"]:,.0f}', "كم / يوم", ""),
                                (f'{t["fuel_sar_year"]:,.0f}', "وقود ريال / سنة", ""), (f'{t["co2_t_year"]:,.1f}', "CO₂ طن / سنة", ""),
                                (f'{t["avg_ride_min"]:.0f} د', "متوسط الرحلة", "")]), unsafe_allow_html=True)
    if SC is not None:
        st.dataframe(SC.round(1), width="stretch")
        st.line_chart(SC.set_index("حد_الرحلة_دقيقة")["مركبات"])
    else:
        st.caption("السيناريوهات ما شُغّلت بعد (خطوة scenarios).")


def tab_quality(R, df):
    st.dataframe(R["scored"]["quality"], width="stretch")
    if R["routes"] is not None:
        nr = df[df["idx"].isin(R["routes"]["nores"])]
        st.markdown(f"**طلاب بدون مسار ({len(nr)})**")
        st.dataframe(nr[["name", "school", "district", "rec_vehicle_ar"]], width="stretch")


def tab_files(demo):
    st.caption("ملفات داخلية فيها أسماء قُصّر (Excel وGPKG وKML الطلاب وجداول السائقين)، لا تُنشر.")
    files = service.output_files(demo)
    if not files:
        return _empty("ما فيه مخرجات بعد.")
    for p in files:
        if p.suffix in (".xlsx", ".kml", ".html", ".gpkg", ".json", ".txt"):
            st.download_button(f"⬇ {p.name}", p.read_bytes(), file_name=p.name, key=_k("f_" + p.name))


# ───────────────────────── نقطة الدخول ─────────────────────────
def render(standalone=False):
    """يرسم الصفحة كاملة. standalone=True يضبط إعداد الصفحة (للتشغيل المستقل فقط، المضيف يضبطه بنفسه)."""
    if standalone:
        st.set_page_config(page_title="النقل المدرسي — جدة", page_icon="🚌", layout="wide")
    st.markdown(style.CSS, unsafe_allow_html=True)
    demo = st.toggle("وضع التجربة (بيانات اصطناعية)", key=_k("demo"), help="لمعاينة الواجهة بدون بيانات حقيقية")
    _header(demo)
    _stepper(demo)
    R = service.results(demo)
    ready = R["scored"] is not None
    tabs = st.tabs(["المدخلات", "التشغيل", "النتائج", "المسارات", "الأسطول والتشغيل", "الجودة", "الملفات"])
    with tabs[0]:
        if demo:
            st.info("وضع التجربة ما يحتاج مدخلات. أطفئ الوضع لإدخال بياناتك.")
        else:
            tab_inputs()
    with tabs[1]:
        tab_run(demo)
    if not ready:
        for t in tabs[2:6]:
            with t:
                _empty("ما فيه نتائج بعد.<br>أضف المدخلات ثم شغّل التحليل من تبويب «التشغيل»، أو فعّل «وضع التجربة» لمعاينة الواجهة.")
    else:
        df = R["scored"]["df"]
        with tabs[2]:
            school, d = _school_filter(df)
            tab_results(R, school, d)
        with tabs[3]:
            tab_routes(R, st.session_state.get(_k("school"), "كل المدارس"), df, demo)
        with tabs[4]:
            tab_fleet(R)
        with tabs[5]:
            tab_quality(R, df)
    with tabs[6]:
        tab_files(demo)
