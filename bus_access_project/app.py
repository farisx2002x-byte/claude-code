"""تشغيل مستقل:  streamlit run app.py
للتضمين كصفحة جانبية في تطبيق مضيف انظر host_page.py وREADME."""
from ui.page import render

render(standalone=True)
