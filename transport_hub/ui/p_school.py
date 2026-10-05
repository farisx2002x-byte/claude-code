"""صفحة النقل المدرسي: تضمّن وحدة bus_access_project كما هي (واجهتها الكاملة)."""

import sys
from pathlib import Path

import streamlit as st

SCHOOL_ROOT = Path(__file__).resolve().parents[2] / "bus_access_project"


def render():
    if not SCHOOL_ROOT.exists():
        st.error("وحدة النقل المدرسي (bus_access_project) غير موجودة بجانب المنصة.")
        return
    if str(SCHOOL_ROOT) not in sys.path:
        sys.path.insert(0, str(SCHOOL_ROOT))
    # أسماء الحزم (config, src, ui) خاصة بالوحدة المدرسية؛ منصة النقل تعيش تحت transport_hub فلا تتعارض
    from ui.page import render as school_render

    school_render()
