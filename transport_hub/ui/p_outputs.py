"""مركز المخرجات: يبني حزمة موثّقة (Excel + تقرير HTML + ملفات GIS + manifest) من نتائج المنصة، مع معاينة وتنزيل."""

import streamlit as st
import streamlit.components.v1 as components

from transport_hub.exports import builder, html_report, package
from transport_hub.exports import excel as XL
from transport_hub.ui import common as U


@st.cache_data(show_spinner="جاري بناء المخرجات…")
def _assemble(sig_, radius, k_new, k_stands, wait):
    meta, sheets, sections, geo_tables = builder.assemble(U.ws(), radius, k_new, k_stands, wait)
    return meta, sheets, sections, geo_tables


def render():
    U.style()
    U.page_header(
        "مركز المخرجات",
        "حزمة تقارير موثّقة جاهزة للتسليم: Excel وتقرير تنفيذي وملفات GIS.",
        "كل ملف في الحزمة يحمل نفس **بصمة التشغيل** والمعاملات ومصادر البيانات (manifest.json)، فيمكن تتبّع أي رقم لمصدره.  \nالتقرير التنفيذي HTML يُطبع PDF من المتصفح (Ctrl+P).",
    )
    have = builder.available(U.ws())
    if not any(have.values()):
        U.empty("لا بيانات بعد. أضف بياناتك من صفحة «البيانات» أو حمّل المدينة التجريبية.")
        return
    labels = {
        "population": "السكان",
        "poi": "نقاط الجذب",
        "gtfs": "النقل العام",
        "trips": "رحلات التاكسي",
        "stands": "مواقف التاكسي",
        "avl": "تتبع AVL",
        "apc": "ركاب APC",
        "register": "سجل الأسطول",
    }
    U.legend([(labels[k] + (" ✓" if v else " ✗"), "#2e9e4f" if v else "#9aa4af") for k, v in have.items()])
    if U.ws().is_demo():
        st.warning("المخرجات ستُوسم «بيانات تجريبية اصطناعية» لأن بعض المدخلات من المدينة التجريبية.")
    c = st.columns(4)
    radius = c[0].number_input("نصف قطر المشي (م)", 200, 1000, 400, 50, key="hub_out_r")
    k_new = c[1].number_input("محطات جديدة مقترحة", 1, 100, 10, key="hub_out_k")
    k_st = c[2].number_input("مواقف تاكسي مقترحة", 1, 50, 8, key="hub_out_s")
    wait = c[3].number_input("انتظار التاكسي المستهدف (د)", 1.0, 20.0, 5.0, key="hub_out_w")
    try:
        meta, sheets, sections, geo_tables = _assemble(U.sig(), int(radius), int(k_new), int(k_st), float(wait))
    except Exception as e:  # noqa: BLE001
        st.error(f"تعذر بناء المخرجات: {e}")
        return
    if not sheets:
        U.empty("لا بيانات كافية: أضف السكان وGTFS أو رحلات التاكسي.")
        return
    U.section("محتويات الحزمة")
    U.kpis([(len(sheets), "أوراق Excel"), (len(sections), "أقسام التقرير"), (len(geo_tables), "طبقات GIS"), (meta["fingerprint"], "بصمة التشغيل")])
    for n in meta.get("notes", []):
        st.caption("• " + n)
    zbytes = package.build_zip(meta, sheets, sections, geo_tables)
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "⬇ الحزمة الكاملة (zip)", zbytes, file_name=f"transport_package_{meta['fingerprint']}.zip", type="primary", width="stretch", key="hub_out_zip"
    )
    import io

    xl = io.BytesIO()
    XL.build_workbook(xl, sheets, meta)
    c2.download_button("⬇ Excel فقط", xl.getvalue(), file_name="التقرير.xlsx", width="stretch", key="hub_out_xl")
    html_doc = html_report.build(meta, sections)
    c3.download_button("⬇ التقرير التنفيذي (HTML)", html_doc.encode("utf-8"), file_name="التقرير_التنفيذي.html", width="stretch", key="hub_out_html")
    tabs = st.tabs(["معاينة التقرير", "أوراق Excel", "ملفات GIS"])
    with tabs[0]:
        components.html(html_doc, height=720, scrolling=True)
    with tabs[1]:
        for sh in sheets:
            with st.expander(f"{sh.name} — {len(sh.df)} صف"):
                U.table(sh.df.head(50))
    with tabs[2]:
        if not geo_tables:
            U.empty("لا طبقات مكانية في هذه البيانات.")
        for name, df in geo_tables.items():
            with st.expander(f"{name} — {len(df)} نقطة"):
                U.table(df)
