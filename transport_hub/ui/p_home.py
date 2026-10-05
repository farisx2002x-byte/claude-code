"""مركز القيادة: صورة سريعة لكل وحدات المنصة."""

import streamlit as st

from transport_hub.admin import scorecard
from transport_hub.ui import common as U


def render():
    U.style()
    st.markdown("## 🚍 منصة النقل — مركز القيادة")
    st.caption("نقل عام · تاكسي · نقل مدرسي · اختيار مواقع · نقاط جذب · إدارة وتقارير")
    have = {k: U.get(k) is not None for k in ("population", "poi", "gtfs", "trips", "stands")}
    if not any(have.values()):
        U.empty("المنصة فارغة. ابدأ من صفحة «البيانات»: ارفع بياناتك أو حمّل المدينة التجريبية لمعاينة كل الوحدات.")
        if st.button("تحميل مدينة تجريبية الآن", type="primary", key="hub_home_demo"):
            from transport_hub.ui.p_data import load_demo

            load_demo()
            st.rerun()
        return
    labels = {"population": "السكان", "poi": "نقاط الجذب", "gtfs": "النقل العام", "trips": "رحلات التاكسي", "stands": "مواقف التاكسي"}
    U.kpis([("✅" if v else "⬜", labels[k]) for k, v in have.items()])
    from transport_hub.ui.p_admin import collect

    vals, tables = collect(U.sig())
    if vals:
        sc = scorecard.build(vals)
        U.kpis(
            [
                ((sc["الحالة"] == "🟢").sum(), "مؤشرات محققة", "ok"),
                ((sc["الحالة"] == "🟡").sum(), "قريبة", "mid"),
                ((sc["الحالة"] == "🔴").sum(), "متأخرة", "hard"),
            ]
        )
        U.table(sc[sc["الحالة"] != "غير متوفر"].drop(columns="key"))
    pop, poi = U.get("population"), U.get("poi")
    if pop is not None:
        layers = [U.scatter(pop, [90, 90, 90], size_col=(pop["pop"] ** 0.5 * 2.2).tolist(), opacity=0.35, pickable=False)]
        feed = U.feed_obj()
        if feed is not None:
            layers.append(
                U.scatter(feed.stops.dropna(subset=["stop_lat"]).rename(columns={"stop_lon": "lon", "stop_lat": "lat"}), [21, 101, 192], size_col=60)
            )
        if poi is not None:
            layers.append(U.scatter(poi, [230, 120, 0], size_col=90))
        U.deck(layers)
        st.caption("رمادي: السكان · أزرق: محطات النقل العام · برتقالي: نقاط الجذب")
