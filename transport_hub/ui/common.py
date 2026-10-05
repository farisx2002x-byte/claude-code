"""مشترك بين صفحات المنصة: مساحة العمل، تحميل البيانات، حالة فارغة، وخرائط pydeck."""
import json

import numpy as np
import pandas as pd
import streamlit as st

from transport_hub.core import data as D
from transport_hub.core import geo
from transport_hub.core.store import Workspace

BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
GRADE_COL = {"0": [150, 150, 150], "1": [215, 48, 39], "2": [252, 141, 89], "3": [254, 224, 139], "4": [166, 217, 106], "5": [102, 189, 99], "6": [26, 152, 80]}

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
    html = "".join(f'<div class="hub-kpi {c if len(i) > 2 else ""}"><div class="v">{i[0]}</div><div class="l">{i[1]}</div></div>'
                   for i in items for c in [i[2] if len(i) > 2 else ""])
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
        labels = {"population": "السكان", "poi": "نقاط الجذب", "gtfs": "جداول النقل العام (GTFS)", "trips": "رحلات التاكسي", "stands": "مواقف التاكسي", "avl": "بيانات التتبع AVL", "apc": "عدّادات الركاب APC", "register": "سجل الأسطول"}
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
    p = proj()
    if center is None:
        df = get("population")
        center = (float(df["lat"].mean()), float(df["lon"].mean())) if df is not None else (21.54, 39.17)
    st.pydeck_chart(pdk.Deck(layers=layers, map_style=BASEMAP, initial_view_state=pdk.ViewState(latitude=center[0], longitude=center[1], zoom=zoom)),
                    height=height)


def scatter(df, color, radius=80, lon="lon", lat="lat", pickable=True, opacity=0.8, size_col=None):
    import pydeck as pdk
    d = df.copy()
    d["_c"] = [list(color)] * len(d) if not callable(color) else [color(r) for r in d.itertuples()]
    return pdk.Layer("ScatterplotLayer", d, get_position=f"[{lon}, {lat}]", get_fill_color="_c", get_radius=size_col or radius, pickable=pickable,
                     opacity=opacity, radius_min_pixels=2)


def table(df, **kw):
    st.dataframe(df, width="stretch", hide_index=True, **kw)


def download_df(label, df, name, key):
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), file_name=name, mime="text/csv", key=key)
