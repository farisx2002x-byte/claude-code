"""صفحة نقاط الجذب: إدارة نقاط الجذب وأوزانها، خريطة الجاذبية، نموذج الجاذبية للرحلات، ومدى وصول النقل العام لها."""

import pandas as pd
import streamlit as st

from transport_hub.core import data as D
from transport_hub.core import demand as DM
from transport_hub.core import geo
from transport_hub.ui import common as U


def render():
    U.style()
    U.page_header(
        "نقاط الجذب",
        "المستشفيات والجامعات والمولات وغيرها: أوزانها وجاذبيتها وقدرة النقل العام على بلوغها.",
        "الوزن يمثل حجم الرحلات التي تولّدها النقطة. نموذج الجاذبية يوزّع رحلات كل منطقة على الجاذبات بدالة أسية للمسافة (β أكبر = رحلات أقصر).",
    )
    d = U.require("population", "poi")
    if d is None:
        return
    pop, poi, proj = d["population"], d["poi"], U.proj()
    tabs = st.tabs(["النقاط والأوزان", "خريطة الجاذبية", "نموذج الجاذبية", "الوصول لها بالنقل العام"])

    with tabs[0]:
        st.caption("عدّل وزن كل فئة (يمثل حجم الرحلات التي تولّدها)، أو أضف نقاطاً جديدة. التعديل يُحفظ في مساحة العمل.")
        cats = poi.groupby("category")["weight"].mean().round(1)
        wt = st.data_editor(cats.rename("الوزن").reset_index(), key="hub_a_w", hide_index=True, width="stretch")
        if st.button("طبّق الأوزان", key="hub_a_apply"):
            m = dict(zip(wt["category"], wt["الوزن"]))
            poi2 = poi.copy()
            poi2["weight"] = poi2["category"].map(m)
            U.ws().save_df("poi", poi2)
            st.cache_data.clear()
            st.rerun()
        st.markdown("**إضافة نقطة جذب**")
        c = st.columns(5)
        nm = c[0].text_input("الاسم", key="hub_a_nm")
        cat = c[1].selectbox("الفئة", sorted(set(D.POI_WEIGHTS) | set(poi["category"])), key="hub_a_cat")
        lo = c[2].number_input("خط الطول", value=float(pop["lon"].mean()), format="%.5f", key="hub_a_lo")
        la = c[3].number_input("خط العرض", value=float(pop["lat"].mean()), format="%.5f", key="hub_a_la")
        if c[4].button("أضف", key="hub_a_add") and nm:
            new = pd.concat(
                [
                    poi[["name", "category", "lon", "lat", "weight"]],
                    pd.DataFrame([dict(name=nm, category=cat, lon=lo, lat=la, weight=D.POI_WEIGHTS.get(cat, 3))]),
                ]
            )
            U.ws().save_df("poi", D.clean_poi(new, proj))
            st.cache_data.clear()
            st.rerun()
        U.table(poi[["name", "category", "weight", "lon", "lat"]].rename(columns={"name": "الاسم", "category": "الفئة", "weight": "الوزن"}))

    with tabs[1]:
        radius = st.slider("نصف قطر التأثير (م)", 300, 3000, 1000, 100, key="hub_a_rad")
        from transport_hub.siting import mcda

        cand = geo.candidate_grid(pop["x"], pop["y"], 250)
        cand["attr"] = mcda.poi_within(cand[["x", "y"]].to_numpy(), poi, radius)
        cand["lon"], cand["lat"] = proj.lonlat(cand["x"], cand["y"])
        mx = max(cand["attr"].max(), 1e-9)
        U.deck(
            [
                U.scatter(cand, lambda r: [255, int(220 - 200 * r.attr / mx), 40], size_col=140, opacity=0.5, pickable=False),
                U.scatter(poi, [30, 30, 140], size_col=(poi["weight"] * 18).tolist(), opacity=0.9),
            ]
        )

    with tabs[2]:
        st.caption("نموذج جاذبية أحادي القيد: الرحلات المنتجة من كل منطقة تتوزع على الجاذبات (وظائف + نقاط جذب) بدالة أسية للمسافة.")
        c = st.columns(3)
        beta = c[0].slider("معامل تأثير المسافة β", 0.05, 1.0, 0.25, 0.05, key="hub_a_beta")
        rate = c[1].number_input("رحلات يومية للفرد", 0.5, 6.0, 2.5, 0.1, key="hub_a_rate")
        try:
            z, od, _ = DM.gravity(pop, poi, beta, rate)
        except ValueError as e:
            st.error(str(e))
            return
        z["lon"], z["lat"] = proj.lonlat(z["x"], z["y"])
        U.kpis(
            [
                (f"{z['production'].sum():,.0f}", "رحلات/يوم"),
                (f"{(z['avg_trip_km'] * z['production']).sum() / z['production'].sum():.1f} كم", "متوسط طول الرحلة"),
            ]
        )
        mx = z["attracted_trips"].max()
        U.deck([U.scatter(z, lambda r: [200, 40, 40], size_col=(z["attracted_trips"] / mx * 400 + 60).tolist(), opacity=0.55)])
        st.markdown("**أعلى تدفقات الرحلات**")
        U.table(od.round(1).rename(columns={"from": "من", "to": "إلى", "trips": "رحلات/يوم", "km": "كم"}))
        st.markdown("**أكثر المناطق جذباً**")
        U.table(
            z.sort_values("attracted_trips", ascending=False)
            .head(10)[["name", "district", "attracted_trips", "avg_trip_km"]]
            .round(1)
            .rename(columns={"name": "المنطقة", "district": "الحي", "attracted_trips": "رحلات جاذبة", "avg_trip_km": "متوسط طول الرحلة كم"})
        )

    with tabs[3]:
        feed = U.feed_obj()
        if feed is None:
            U.empty("يحتاج GTFS لحساب وصول النقل العام لنقاط الجذب.")
        else:
            from transport_hub.transit import csa
            from transport_hub.ui.p_transit import _router

            c = st.columns(3)
            hour = c[0].slider("ساعة الانطلاق", 5.0, 22.0, 8.0, 0.5, key="hub_a_h")
            mins = c[1].slider("الحد الأقصى (د)", 15, 90, 45, 5, key="hub_a_m")
            r = _router(U.sig())
            sample = pop.sort_values("pop", ascending=False).head(60).reset_index(drop=True)
            res = csa.opportunities(r, sample, poi.assign(n=1), hour, mins, value_cols=("weight",), max_origins=60)
            col = f"reach_weight_{mins}"
            tot = poi["weight"].sum()
            res["share"] = 100 * res[col] / tot
            res["lon"], res["lat"] = proj.lonlat(res["x"], res["y"])
            U.kpis(
                [(f"{res['share'].mean():.0f}%", "متوسط جاذبية يمكن بلوغها"), (f"{(res['share'] < 25).sum()}", "مناطق كبيرة معزولة (<25%)", "hard")]
            )
            U.deck([U.scatter(res, lambda r_: [int(255 * (1 - r_.share / 100)), int(200 * r_.share / 100) + 40, 60], size_col=260, opacity=0.7)])
            U.table(
                res.sort_values("share")[["name", "pop", "share"]]
                .head(15)
                .round(1)
                .rename(columns={"name": "المنطقة", "pop": "السكان", "share": "% من الجاذبية بالوصول"})
            )
            st.caption("الحساب على أكبر 60 منطقة سكاناً للسرعة.")
