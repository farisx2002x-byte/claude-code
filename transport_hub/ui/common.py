"""مشترك بين صفحات المنصة: مساحة العمل، تحميل البيانات، حالة فارغة، وخرائط pydeck."""

import functools
import json

import pandas as pd
import streamlit as st

from transport_hub.core import geo
from transport_hub.core.log import get_logger
from transport_hub.core.store import Workspace
from transport_hub.exports import dictionary as DICT

BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
GRADE_COL = {
    "0": [150, 150, 150],
    "1": [215, 48, 39],
    "2": [252, 141, 89],
    "3": [254, 224, 139],
    "4": [166, 217, 106],
    "5": [102, 189, 99],
    "6": [26, 152, 80],
}

CSS = """
<style>
[data-testid="stMainBlockContainer"] {direction: rtl; text-align: right;}
[data-testid="stMainBlockContainer"] [data-testid="stDataFrame"], [data-testid="stMainBlockContainer"] [data-testid="stDeckGlJsonChart"],
[data-testid="stMainBlockContainer"] [data-testid="stVegaLiteChart"] {direction: ltr;}
.hub-kpis {display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:8px 0 16px;}
.hub-kpi {padding:12px 14px; border-radius:12px; border:1px solid rgba(128,128,128,.25); background:rgba(128,128,128,.06);}
.hub-kpi .v {font-size:1.5rem; font-weight:700; line-height:1.2;} .hub-kpi .l {opacity:.7; font-size:.85rem;}
.hub-kpi.ok {border-right:4px solid #2e9e4f;} .hub-kpi.mid {border-right:4px solid #e0a800;} .hub-kpi.hard {border-right:4px solid #d1383d;}
.hub-empty {text-align:center; padding:28px 12px; border:1px dashed rgba(128,128,128,.4); border-radius:14px; opacity:.85;}
.hub-note {font-size:.8rem; opacity:.65;}
[data-testid="stMarkdownContainer"] {direction: rtl; text-align: right;}
.hub-head > div, .hub-sec, .hub-sub {direction: rtl; text-align: right;}
.hub-head {display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin:0 0 6px;}
.hub-head h2 {margin:0; font-size:1.6rem;} .hub-sub {opacity:.7; margin:2px 0 10px; font-size:.95rem;}
.hub-pill {border-radius:999px; padding:2px 12px; font-size:.78rem; border:1px solid rgba(128,128,128,.4); white-space:nowrap;}
.hub-pill.demo {background:rgba(224,168,0,.18); border-color:#e0a800;} .hub-pill.ok {background:rgba(46,158,79,.14); border-color:#2e9e4f;}
.hub-sec {margin:18px 0 4px; font-size:1.1rem; font-weight:700; border-right:4px solid #1565c0; padding-right:8px;}
.hub-legend {display:flex; flex-wrap:wrap; gap:6px 14px; font-size:.8rem; margin:4px 0 10px; opacity:.9;}
.hub-legend i {display:inline-block; width:11px; height:11px; border-radius:50%; margin-left:5px; vertical-align:middle;}
.hub-err {border:1px solid #d1383d; background:rgba(209,56,61,.08); border-radius:10px; padding:12px 14px;}
</style>
"""


@st.cache_resource
def ws():
    return Workspace()


def sig():
    """توقيع حالة مساحة العمل (يبطل الكاش عند أي تحديث للبيانات)."""
    return json.dumps(ws().meta(), sort_keys=True)


def style():
    st.markdown(CSS, unsafe_allow_html=True)


def kpis(items):
    """items: قائمة (قيمة, عنوان, صنف اختياري ok/mid/hard)."""
    html = "".join(
        f'<div class="hub-kpi {c if len(i) > 2 else ""}"><div class="v">{i[0]}</div><div class="l">{i[1]}</div></div>'
        for i in items
        for c in [i[2] if len(i) > 2 else ""]
    )
    st.markdown(f'<div class="hub-kpis">{html}</div>', unsafe_allow_html=True)


def empty(msg):
    st.markdown(f'<div class="hub-empty">{msg}</div>', unsafe_allow_html=True)


def proj():
    e = ws().obj("proj_epsg")
    return geo.Projector(e) if e else None


@st.cache_data(show_spinner=False)
def _load(sig_, name):
    w = ws()
    d = w.df(name)
    return d if d is not None else w.obj(name)


def get(name):
    return _load(sig(), name)


def require(*names, what=""):
    """يرجع dict بالبيانات المطلوبة، أو يعرض حالة فارغة ويرجع None."""
    out = {n: get(n) for n in names}
    miss = [n for n, v in out.items() if v is None]
    if miss:
        labels = {
            "population": "السكان",
            "poi": "نقاط الجذب",
            "gtfs": "جداول النقل العام (GTFS)",
            "trips": "رحلات التاكسي",
            "stands": "مواقف التاكسي",
            "avl": "بيانات التتبع AVL",
            "apc": "عدّادات الركاب APC",
            "register": "سجل الأسطول",
        }
        empty(f"هذه الصفحة تحتاج: {'، '.join(labels.get(m, m) for m in miss)}.<br>أضفها من صفحة «البيانات» أو حمّل المدينة التجريبية. {what}")
        return None
    return out


def feed_obj():
    from transport_hub.transit import gtfs

    t = get("gtfs")
    return gtfs.from_tables({k: v for k, v in t.items()}) if t is not None else None


# ───────── خرائط ─────────
def deck(layers, center=None, zoom=11, height=520):
    import pydeck as pdk

    if center is None:
        df = get("population")
        center = (float(df["lat"].mean()), float(df["lon"].mean())) if df is not None else (21.54, 39.17)
    st.pydeck_chart(
        pdk.Deck(layers=layers, map_style=BASEMAP, initial_view_state=pdk.ViewState(latitude=center[0], longitude=center[1], zoom=zoom)),
        height=height,
    )


def scatter(df, color, radius=80, lon="lon", lat="lat", pickable=True, opacity=0.8, size_col=None):
    import pydeck as pdk

    d = df.copy()
    d["_c"] = [list(color)] * len(d) if not callable(color) else [color(r) for r in d.itertuples()]
    return pdk.Layer(
        "ScatterplotLayer",
        d,
        get_position=f"[{lon}, {lat}]",
        get_fill_color="_c",
        get_radius=size_col or radius,
        pickable=pickable,
        opacity=opacity,
        radius_min_pixels=2,
    )


_NUM = {"int": "%d", "dec1": "%.1f", "dec2": "%.2f", "dec5": "%.5f", "pct": "%.1f%%", "ratio": "percent"}


def column_config(df):
    """إعداد أعمدة الجدول من قاموس البيانات: تسمية عربية بوحدة، شرح عند التمرير، وصيغة أرقام."""
    cfg = {}
    for c in df.columns:
        if c not in DICT.COLUMNS:
            continue
        lab, desc, unit, fmt = DICT.COLUMNS[c]
        label = f"{lab} ({unit})" if unit and unit not in ("عدد", "") else lab
        if fmt in _NUM and pd.api.types.is_numeric_dtype(df[c]):
            cfg[c] = st.column_config.NumberColumn(label, help=desc or None, format=_NUM[fmt])
        elif fmt == "flag":
            cfg[c] = st.column_config.CheckboxColumn(label, help=desc or None)
        else:
            cfg[c] = st.column_config.TextColumn(label, help=desc or None)
    return cfg


def table(df, **kw):
    cfg = {**column_config(df), **kw.pop("column_config", {})}
    st.dataframe(df, width="stretch", hide_index=True, column_config=cfg, **kw)


def page_header(title, subtitle="", help_md=None):
    """ترويسة موحدة للصفحة: العنوان، وصف، شارة (تجريبي/حقيقي)، وشرح قابل للطي."""
    demo = ws().is_demo()
    pill = '<span class="hub-pill demo">بيانات تجريبية</span>' if demo else ""
    st.markdown(f'<div class="hub-head"><div><h2>{title}</h2><div class="hub-sub">{subtitle}</div></div>{pill}</div>', unsafe_allow_html=True)
    if help_md:
        with st.expander("كيف تقرأ هذه الصفحة؟"):
            st.markdown(help_md)


def section(title):
    st.markdown(f'<div class="hub-sec">{title}</div>', unsafe_allow_html=True)


def legend(items):
    """مفتاح خريطة: items = [(الاسم, اللون hex أو [r,g,b])]."""

    def hexc(c):
        return c if isinstance(c, str) else "#{:02x}{:02x}{:02x}".format(*c)

    st.markdown(
        '<div class="hub-legend">' + "".join(f'<span><i style="background:{hexc(c)}"></i>{n}</span>' for n, c in items) + "</div>",
        unsafe_allow_html=True,
    )


def guard(fn):
    """يغلّف دالة صفحة: أي خطأ غير متوقع يظهر برسالة عربية واضحة مع التفاصيل التقنية قابلة للطي، ويُسجَّل، بدل تعطّل الصفحة."""
    log = get_logger("ui")

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except st.errors.StreamlitAPIException:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("page error in %s", fn.__module__)
            st.markdown(
                '<div class="hub-err"><b>حدث خطأ غير متوقع في هذه الصفحة.</b><br>تحقق من البيانات المحمّلة (صفحة «البيانات» ← فحص الجودة) ثم أعد المحاولة.</div>',
                unsafe_allow_html=True,
            )
            with st.expander("التفاصيل التقنية"):
                st.code(f"{type(e).__name__}: {e}")

    return wrapper


def download_df(label, df, name, key):
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), file_name=name, mime="text/csv", key=key)
