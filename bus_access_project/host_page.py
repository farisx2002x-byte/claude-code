"""صفحة جاهزة للتضمين في تطبيق Streamlit مضيف (بدون set_page_config، المضيف هو اللي يضبطه):

    # في التطبيق المضيف
    pg = st.navigation([
        st.Page("home.py", title="الرئيسية"),
        st.Page("bus_access_project/host_page.py", title="النقل المدرسي", icon="🚌", url_path="school-transport"),
    ])
    pg.run()
"""
from ui.page import render

render()
