"""صفحة الأداء الفعلي: الالتزام بالمواعيد، انتظام التردد، الركاب، وتوصيات تشغيلية من بيانات AVL وAPC."""

import pandas as pd
import streamlit as st

from transport_hub.ops import performance as P
from transport_hub.ui import common as U


@st.cache_data(show_spinner="جاري تحليل بيانات التتبع…")
def _analyze(sig_):
    avl = P.clean_avl(U.get("avl"))
    feed = U.feed_obj()
    otp = P.on_time(avl)
    _, reg = P.headway_regularity(avl)
    rt = P.running_time(avl, feed)
    return avl, otp, reg, rt


def render():
    U.style()
    U.page_header(
        "الأداء الفعلي",
        "الالتزام بالمواعيد وانتظام التردد والركاب من بيانات التتبع والعدّادات.",
        "في الموعد = بين −1 و+5 دقائق من الجدول. EWT هو ما يزيده انتظار الراكب الفعلي عن المجدول. التكدّس: فاصل < 25% من المجدول.",
    )
    if U.get("avl") is None and U.get("apc") is None:
        U.empty("هذه الصفحة تحتاج بيانات التتبع (AVL) و/أو عدّادات الركاب (APC). أضفها من «البيانات» ← تبويب التشغيل، أو حمّل المدينة التجريبية.")
        return
    tabs = st.tabs(["الالتزام بالمواعيد", "انتظام التردد", "الركاب", "توصيات"])
    avl = otp = reg = rt = None
    if U.get("avl") is not None:
        avl, otp, reg, rt = _analyze(U.sig())
    apc_sum = None
    if U.get("apc") is not None:
        apc_sum = P.apc_summary(P.clean_apc(U.get("apc")), 72)

    with tabs[0]:
        if avl is None:
            U.empty("لا بيانات AVL.")
        else:
            tot = avl.assign(late=avl["delay_s"] > P.LATE_S, early=avl["delay_s"] < -P.EARLY_S)
            ot = 100 * (1 - tot["late"].mean() - tot["early"].mean())
            U.kpis(
                [
                    (f"{ot:.0f}%", "في الموعد", "ok" if ot >= 85 else "mid" if ot >= 75 else "hard"),
                    (f"{100 * tot['late'].mean():.0f}%", "متأخر (> 5 د)", "hard"),
                    (f"{100 * tot['early'].mean():.1f}%", "مبكر (> 1 د)"),
                    (f"{avl['delay_s'].mean() / 60:.1f} د", "متوسط التأخير"),
                    (f"{len(avl):,}", "مشاهدات"),
                ]
            )
            U.table(
                otp.rename(
                    columns={
                        "route_id": "الخط",
                        "observations": "مشاهدات",
                        "early_pct": "% مبكر",
                        "late_pct": "% متأخر",
                        "avg_delay_min": "متوسط التأخير د",
                        "p90_delay_min": "التأخير 90% د",
                        "on_time_pct": "% في الموعد",
                    }
                )
            )
            c1, c2 = st.columns(2)
            c1.caption("التأخير حسب الساعة (د)")
            c1.line_chart(
                P.delay_profile(avl)
                .set_index("hour")[["avg_delay_min", "p90_delay_min"]]
                .rename(columns={"avg_delay_min": "متوسط التأخير", "p90_delay_min": "التأخير 90%"})
                .rename_axis("الساعة")
            )
            c2.caption("زمن الرحلة الفعلي مقابل المجدول")
            c2.dataframe(
                rt.rename(
                    columns={
                        "route_id": "الخط",
                        "sched_min": "المجدول د",
                        "actual_avg_min": "الفعلي (متوسط)",
                        "actual_pctl_min": "الفعلي (85%)",
                        "recommended_extra_min": "زمن إضافي مقترح",
                    }
                ),
                hide_index=True,
                width="stretch",
            )

    with tabs[1]:
        if reg is None or reg.empty:
            U.empty("لا بيانات كافية لحساب الانتظام.")
        else:
            U.kpis(
                [
                    (f"{reg['ewt_min'].mean():.2f} د", "الانتظار الإضافي EWT (متوسط)"),
                    (f"{reg['bunched_pct'].mean():.0f}%", "فواصل متكدّسة"),
                    (f"{reg['gap_pct'].mean():.0f}%", "فجوات كبيرة"),
                ]
            )
            U.table(reg.rename(columns={"route_id": "الخط", "ewt_min": "EWT د", "bunched_pct": "% تكدّس", "gap_pct": "% فجوات"}))
            st.caption("EWT: متوسط ما يزيده الانتظار الفعلي عن المجدول (Σh² ÷ 2Σh). التكدّس: فاصل < 25% من المجدول. الفجوة: > 150%.")

    with tabs[2]:
        if apc_sum is None:
            U.empty("لا بيانات ركاب APC.")
        else:
            U.kpis(
                [
                    (f"{apc_sum['pax_day'].sum():,.0f}", "ركاب/يوم (مرصودة)"),
                    (f"{apc_sum['avg_max_load'].mean():.0f}", "متوسط أقصى حمل للرحلة"),
                    (f"{apc_sum['crowded_trips_pct'].mean():.1f}%", "رحلات مزدحمة", "hard" if apc_sum["crowded_trips_pct"].mean() > 5 else "ok"),
                ]
            )
            U.table(
                apc_sum.rename(
                    columns={
                        "route_id": "الخط",
                        "pax_day": "ركاب/يوم",
                        "avg_max_load": "متوسط أقصى حمل",
                        "trips": "رحلات",
                        "crowded_trips_pct": "% مزدحمة",
                    }
                )
            )
            st.caption("الركاب هنا من عيّنة الرحلات في الملف، فالأرقام اليومية أدنى من الواقع لو الملف جزئي.")
            feed = U.feed_obj()
            pop = U.get("population")
            if feed is not None and pop is not None:
                from transport_hub.transit import coverage as COV
                from transport_hub.transit import planning, ridership, service

                st_ = COV.stops_frame(feed, U.proj())
                sr = service.stop_route_freq(feed)
                _, cov = planning.scenario_kpis(pop, st_, sr, access=U.access())
                _, _, br = ridership.estimate(cov, st_, sr)
                m, factor = P.calibrate(apc_sum, br)
                st.markdown("**معايرة نموذج تقدير الركاب بالأرقام الفعلية**")
                U.table(m.round(2).rename(columns={"route_id": "الخط", "actual": "الفعلي", "estimated": "المقدّر", "factor": "المعامل"}))
                st.caption(
                    f"المعامل الوسيط {factor:.2f}: اضرب تقدير الحصة به (أو عدّل max_share) لتقترب الأرقام من الواقع. مرجع: عيّنة الرحلات في الملف."
                )

    with tabs[3]:
        for r in P.recommend(otp if otp is not None else pd.DataFrame(columns=["route_id", "late_pct"]), rt, reg, apc_sum):
            st.markdown(f"- {r}")
