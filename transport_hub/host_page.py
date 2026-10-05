"""للتضمين في تطبيق Streamlit مضيف كصفحات جانبية:

from transport_hub.app import PAGES
pages = [st.Page(fn, title=t, icon=i, url_path=u) for t, i, u, fn in PAGES]      # كل الوحدات
# أو وحدة واحدة:  st.Page(transport_hub.ui.p_transit.render, title="النقل العام")
"""
