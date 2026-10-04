"""صفحة التاكسي: نظرة عامة، النقاط الساخنة، العرض والطلب وإعادة التوزيع، حجم الأسطول، مواقع المواقف."""
import numpy as np
import pandas as pd
import streamlit as st

from transport_hub.taxi import demand, fleet, stands, supply
from transport_hub.ui import common as U


def render():
    U.style()
    st.markdown("### التاكسي")
    d = U.require("trips", "population")
    if d is None:
        return
    trips, zones, proj = d["trips"], d["population"], U.proj()
    tabs = st.tabs(["نظرة عامة", "النقاط الساخنة", "العرض والطلب", "حجم الأسطول", "مواقف التاكسي"])

    with tabs[0]:
        k = fleet.kpis(trips)
        U.kpis([(v, n) for n, v in k.items()][:8])
        c1, c2 = st.columns(2)
        c1.caption("الرحلات لكل ساعة (متوسط يومي)")
        c1.bar_chart(demand.hourly_profile(trips).set_index("hour")["trips_per_day"])
        c2.caption("الرحلات حسب اليوم")
        c2.bar_chart(demand.dow_profile(trips).set_index("day")["trips_per_day"])
        fl = demand.od_flows(trips, zones)
        if len(fl):
            st.markdown("**أعلى تدفقات الأصل ← الوجهة**")
            U.table(fl.rename(columns={"from": "من", "to": "إلى", "trips": "رحلات", "trips_per_day": "رحلات/يوم"}).round(2))

    with tabs[1]:
        c = st.columns(3)
        hrs = c[0].slider("الساعات", 0, 24, (0, 24), key="hub_x_hrs")
        share = c[1].slider("حصة الطلب التي تغطيها النقاط", 0.2, 0.9, 0.5, 0.05, key="hub_x_share")
        cell = c[2].select_slider("حجم الخلية (م)", [200, 300, 400, 500, 750], 400, key="hub_x_cell")
        hours = set(range(hrs[0], max(hrs[1], hrs[0] + 1)))
        hs = demand.hotspots(trips, cell, share, hours, proj)
        if hs.empty:
            U.empty("ما فيه رحلات في هذه الساعات.")
        else:
            U.kpis([(len(hs), "نقاط ساخنة"), (f'{hs["share_pct"].sum():.0f}%', "من الطلب"), (f'{hs["trips_per_day"].iloc[0]:.0f}', "رحلات/يوم في الأولى")])
            U.deck([U.scatter(hs, [220, 50, 40], size_col=(hs["trips_per_day"] ** 0.5 * 25).tolist(), opacity=0.55)])
            U.table(hs[["rank", "trips_per_day", "share_pct", "peak_hour", "cells", "lon", "lat"]].round(2).rename(columns={
                "rank": "الرتبة", "trips_per_day": "رحلات/يوم", "share_pct": "% من الطلب", "peak_hour": "ساعة الذروة", "cells": "خلايا"}))

    with tabs[2]:
        hour = st.slider("الساعة", 0, 23, 8, key="hub_x_hour")
        bal = supply.zone_balance(trips, zones, hour)
        bal["lon"], bal["lat"] = proj.lonlat(bal["x"], bal["y"])
        U.kpis([(f'{bal["demand"].sum():.0f}', "طلب/ساعة"), (f'{bal["supply"].sum():.0f}', "عرض/ساعة"),
                (int((bal["balance"] < -0.5).sum()), "مناطق عجز", "hard"), (int((bal["balance"] > 0.5).sum()), "مناطق فائض", "ok")])
        U.deck([U.scatter(bal, lambda r: [209, 56, 61] if r.balance < -0.5 else ([46, 158, 79] if r.balance > 0.5 else [170, 170, 170]),
                          size_col=(np.abs(bal["balance"]) * 60 + 80).tolist(), opacity=0.7)])
        plan = supply.rebalance_plan(bal)
        st.markdown("**خطة إعادة التوزيع (أقل مسافة كلية)**")
        if plan.empty:
            st.caption("لا حاجة لإعادة توزيع في هذه الساعة.")
        else:
            U.kpis([(int(plan["vehicles"].sum()), "مركبات تُنقل"), (f'{(plan["vehicles"] * plan["km"]).sum():.0f}', "كم إجمالي")])
            U.table(plan.rename(columns={"from": "من", "to": "إلى", "vehicles": "مركبات", "km": "كم"}))
        st.caption("العرض هنا تقدير من التوصيلات في الساعة السابقة؛ زوّد المنصة ببيانات مواقع المركبات اللحظية لنتائج أدق.")

    with tabs[3]:
        c = st.columns(4)
        wait = c[0].number_input("الانتظار المستهدف (د)", 1.0, 20.0, 5.0, key="hub_x_wait")
        dh = c[1].number_input("وقت الوصول للراكب (د)", 0.0, 20.0, 6.0, key="hub_x_dh")
        ut = c[2].slider("سقف الإشغال", 0.4, 0.95, 0.75, 0.05, key="hub_x_ut")
        cur = c[3].number_input("الأسطول الحالي", 0, 100000, int(trips["vehicle_id"].nunique()) if "vehicle_id" in trips else 0, key="hub_x_cur")
        fh = fleet.fleet_by_hour(trips, wait, dh, ut)
        peak = int(fh["needed"].max())
        U.kpis([(peak, "المطلوب في الذروة"), (cur, "الأسطول الحالي"), (peak - cur, "الفرق", "hard" if peak > cur else "ok"),
                (f'{fleet.avg_wait_min(cur, float(fh["trips"].max()), float(trips["duration_min"].mean()) + dh):.1f} د' if cur else "—", "الانتظار المتوقع بالأسطول الحالي في الذروة")])
        st.bar_chart(fh.set_index("hour")[["needed_wait", "needed_util"]].rename(columns={"needed_wait": "حسب الانتظار", "needed_util": "حسب الإشغال"}))

    with tabs[4]:
        st_df = U.get("stands")
        ex = st_df[["x", "y"]].to_numpy() if st_df is not None else np.zeros((0, 2))
        c = st.columns(3)
        n = c[0].number_input("عدد المواقف الجديدة", 1, 50, 8, key="hub_x_nst")
        rad = c[1].number_input("مسافة المشي (م)", 100, 800, 300, 50, key="hub_x_srad")
        cov0 = stands.stand_coverage(trips, ex, rad)
        sel, (b, a) = stands.suggest_stands(trips, ex, int(n), rad, proj=proj)
        U.kpis([(f"{cov0:.0f}%", "الالتقاطات المغطاة حالياً"), (f"{a:.0f}%", "بعد المواقع الجديدة", "ok"), (len(ex), "مواقف حالية")])
        layers = [U.scatter(sel, [230, 120, 0], size_col=140)]
        if st_df is not None:
            layers.append(U.scatter(st_df, [21, 101, 192], size_col=120))
        U.deck(layers)
        U.table(sel[["rank", "trips_per_day", "cum_covered_pct", "lon", "lat"]].round(2))
        U.download_df("تنزيل المواقع (CSV)", sel, "taxi_stands.csv", "hub_x_dl")
