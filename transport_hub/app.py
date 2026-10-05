"""منصة النقل — تشغيل مستقل:  streamlit run transport_hub/app.py
للتضمين كصفحة جانبية في تطبيق مضيف: st.Page("transport_hub/host_page.py") أو استدعاء render_hub()."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from transport_hub.ui import (p_admin, p_attractors, p_data, p_home, p_ops, p_perf, p_school, p_siting, p_taxi, p_transit)  # noqa: E402

PAGES = [
    ("الرئيسية", "🏠", "home", p_home.render),
    ("البيانات", "🗂️", "data", p_data.render),
    ("النقل العام", "🚌", "transit", p_transit.render),
    ("التشغيل والجدولة", "🛠️", "ops", p_ops.render),
    ("الأداء الفعلي", "⏱️", "performance", p_perf.render),
    ("التاكسي", "🚕", "taxi", p_taxi.render),
    ("النقل المدرسي", "🎒", "school", p_school.render),
    ("اختيار المواقع", "📍", "siting", p_siting.render),
    ("نقاط الجذب", "⭐", "attractors", p_attractors.render),
    ("الإدارة", "📊", "admin", p_admin.render),
]


def main():
    st.set_page_config(page_title="منصة النقل", page_icon="🚍", layout="wide")
    pages = [st.Page(fn, title=t, icon=i, url_path=u) for t, i, u, fn in PAGES]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
