"""صفحة التشغيل والجدولة: جدولة المركبات، قطع السائقين، سجل الأسطول والصيانة، والتحول للكهرباء."""
import numpy as np
import pandas as pd
import streamlit as st

from transport_hub.ops import blocking as B
from transport_hub.ops import fleetmgmt as F
from transport_hub.ui import common as U


@st.cache_data(show_spinner="جاري جدولة المركبات…")
def _blocks(sig_, layover, gap, dh, minimize):
    feed, proj = U.feed_obj(), U.proj()
    trips = B.trip_endpoints(feed, proj)
    return B.build_blocks(trips, layover, gap, minimize, None, dh) + (trips,)


def render():
    U.style()
    st.markdown("### التشغيل والجدولة")
    d = U.require("gtfs", "population")
    if d is None:
        return
    tabs = st.tabs(["جدولة المركبات", "السائقون", "الأسطول والصيانة", "التحول الكهربائي"])
    with tabs[0]:
        c = st.columns(4)
        layover = c[0].number_input("استراحة النهاية (د)", 0, 30, 5, key="hub_o_lay")
        gap = c[1].number_input("أقصى انتظار بين رحلتين (د)", 10, 240, 90, key="hub_o_gap")
        dh = c[2].number_input("أقصى توصيل فارغ (كم)", 0.0, 20.0, 3.0, 0.5, key="hub_o_dh")
        mn = c[3].checkbox("تقليل الانتظار والتوصيل", True, key="hub_o_min", help="بين الحلول بنفس عدد المركبات يختار الأقل تكلفة (حتى 2500 رحلة)")
        blocks, s, trips = _blocks(U.sig(), layover, gap, dh, mn)
        U.kpis([(s["vehicles"], "مركبات مطلوبة"), (s["theoretical_min"], "الحد النظري الأدنى"), (s["trips"], "رحلات"),
                (f'{s["utilization"] * 100:.0f}%', "نسبة الاستخدام (خدمة ÷ فترة التشغيل)"), (f'{s["deadhead_km"]}', "كم توصيل فارغ"), (f'{s["idle_h"]}', "ساعات انتظار")])
        if s["vehicles"] > s["theoretical_min"]:
            st.caption(f'الفرق عن الحد النظري ({s["vehicles"] - s["theoretical_min"]} مركبة) سببه التقاء النهايات والاستراحات؛ جرّب رفع أقصى توصيل أو تقليل الاستراحة.')
        # المركبات العاملة في كل ساعة
        hrs = range(int(trips["start"].min() // 3600), int(trips["end"].max() // 3600) + 1)
        act = [int(((blocks.groupby("vehicle")["start"].min() <= (h + 1) * 3600) & (blocks.groupby("vehicle")["end"].max() >= h * 3600)).sum()) for h in hrs]
        st.caption("مركبات في الخدمة حسب الساعة")
        st.bar_chart(pd.Series(act, index=list(hrs), name="مركبات"))
        vt = B.vehicle_table(blocks)
        U.table(vt.round(1).rename(columns={"vehicle": "المركبة", "trips": "رحلات", "first_start": "أول انطلاق", "last_end": "آخر وصول", "km": "كم", "routes": "الخطوط", "span_h": "فترة التشغيل س", "in_service_h": "ساعات الخدمة"}))
        U.download_df("تنزيل جدول المركبات والرحلات (CSV)", blocks[["vehicle", "seq", "trip_id", "route_id", "direction_id", "start", "end", "km"]], "vehicle_blocks.csv", "hub_o_dl")

    with tabs[1]:
        blocks, s, trips = _blocks(U.sig(), 5, 90, 3.0, True)
        c = st.columns(4)
        md = c[0].number_input("أقصى قيادة متواصلة (س)", 2.0, 8.0, 4.5, 0.5, key="hub_o_md")
        mb = c[1].number_input("أقل استراحة (د)", 5, 60, 15, key="hub_o_mb")
        mdu = c[2].number_input("أقصى وردية (س)", 4.0, 14.0, 9.0, 0.5, key="hub_o_mdu")
        so = c[3].number_input("تسجيل دخول/خروج (د)", 0, 45, 15, key="hub_o_so")
        dd, ds = B.duties(blocks, md, mb, mdu, so)
        if dd.empty:
            U.empty("ما فيه قطع عمل.")
        else:
            U.kpis([(ds["pieces"], "قطع عمل"), (ds["drive_h"], "ساعات قيادة"), (ds["paid_h"], "ساعات مدفوعة"), (ds["min_drivers"], "أقل عدد سائقين تقريباً"),
                    (ds["violations"], "مخالفات", "hard" if ds["violations"] else "ok")])
            st.caption("قطع العمل تُقطع عند فرص التبديل في الاستراحات. تركيب القطع في ورديات كاملة (مع تبديل الأماكن واتفاقيات العمل) يحتاج مجدول أطقم متخصص؛ الرقم أعلاه حد أدنى تقريبي.")
            U.table(dd.round(2).rename(columns={"vehicle": "المركبة", "start": "من", "end": "إلى", "drive_h": "قيادة س", "trips": "رحلات", "violation": "مخالفة", "span_h": "المدة س"}))

    with tabs[2]:
        reg = U.get("register")
        if reg is None:
            U.empty("أضف سجل الأسطول من صفحة «البيانات» (تبويب التشغيل).")
        else:
            blocks, s, trips = _blocks(U.sig(), 5, 90, 3.0, True)
            kmd = float(blocks.groupby("vehicle")["km"].sum().mean())
            kd = st.number_input("كم/يوم لكل مركبة", 10.0, 1000.0, round(kmd, 0), key="hub_o_kmd")
            m = F.maintenance(F.clean_register(reg), kd)
            vc = m["status"].value_counts()
            U.kpis([(len(m), "مركبات"), (int(vc.get("متأخرة", 0)), "صيانة متأخرة", "hard"), (int(vc.get("قريبة", 0)), "قريبة", "mid"), (int(vc.get("سليمة", 0)), "سليمة", "ok"),
                    (f'{m["age"].mean():.1f}', "متوسط العمر (سنة)")])
            c1, c2 = st.columns(2)
            c1.caption("توزيع أعمار الأسطول"); c1.bar_chart(F.age_profile(reg).set_index("العمر"))
            c2.caption("حالة الصيانة"); c2.bar_chart(vc)
            U.table(m.sort_values("status")[["vehicle_id", "type", "age", "km_since", "days_since", "status", "next_service"]].rename(columns={
                "vehicle_id": "المركبة", "type": "النوع", "age": "العمر", "km_since": "كم منذ آخر صيانة", "days_since": "يوم منذ آخر صيانة", "status": "الحالة", "next_service": "الصيانة القادمة"}))

    with tabs[3]:
        blocks, s, trips = _blocks(U.sig(), 5, 90, 3.0, True)
        c = st.columns(5)
        kwh = c[0].number_input("استهلاك كيلوواط/كم", 0.8, 3.0, 1.6, 0.1, key="hub_o_kwh")
        bat = c[1].number_input("البطارية (kWh)", 100, 800, 350, 10, key="hub_o_bat")
        usable = c[2].slider("القابل للاستخدام", 0.5, 1.0, 0.8, 0.05, key="hub_o_use")
        kw = c[3].number_input("قدرة الشاحن (kW)", 20, 600, 150, 10, key="hub_o_kw")
        win = c[4].number_input("نافذة الشحن الليلية (س)", 2.0, 12.0, 6.0, 0.5, key="hub_o_win")
        v, es = F.ev_feasibility(blocks, kwh, bat, usable, 0.1, kw, win)
        U.kpis([(f'{es["feasible_pct"]}%', "مركبات يكفيها شحن ليلي واحد", "ok" if es["feasible_pct"] > 70 else "mid"), (es["chargers_needed"], "شواحن مطلوبة"),
                (f'{es["depot_peak_kw"]:,} kW', "ذروة قدرة المستودع"), (es["energy_mwh_day"], "طاقة يومية MWh")])
        st.markdown("**مقارنة التكلفة الإجمالية لمركبة (ديزل مقابل كهرباء)**")
        c = st.columns(3)
        km_y = c[0].number_input("كم/سنة للمركبة", 10_000, 200_000, int(v["km"].mean() * 300), 5000, key="hub_o_kmy")
        yrs = c[1].number_input("السنوات", 3, 20, 12, key="hub_o_yrs")
        ev_price = c[2].number_input("سعر الباص الكهربائي", 500_000, 3_000_000, 1_450_000, 50_000, key="hub_o_evp")
        t = F.tco(km_y, int(yrs), ev=dict(price=ev_price, kwh_km=kwh, kwh_price=0.18, maint_km=0.45, charger=120_000))
        U.kpis([(f'{t["diesel_total"]:,.0f}', "ديزل (قيمة حالية)"), (f'{t["ev_total"]:,.0f}', "كهرباء (قيمة حالية)"),
                (f'{t["saving"]:,.0f}', "الوفر", "ok" if t["saving"] > 0 else "hard"), (f'{t["payback_years"]:.1f} سنة' if t["payback_years"] == t["payback_years"] else "—", "فترة الاسترداد")])
        st.caption("الأسعار والتعرفة افتراضية وتقديرية: عدّلها بعروض الموردين وتعرفة الكهرباء الفعلية.")
        U.table(v.round(1).rename(columns={"vehicle": "المركبة", "km": "كم/يوم", "kwh_day": "kWh/يوم", "feasible": "تكفيها البطارية", "needs_midday_charge_kwh": "شحن إضافي kWh", "charge_h": "ساعات شحن"}).drop(columns="service_km"))
