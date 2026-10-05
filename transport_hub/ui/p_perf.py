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


def _congestion_tab():
    import pydeck as pdk

    from transport_hub.core import congestion as CG
    from transport_hub.core.access import load_access

    st.caption(
        "يربط الازدحام بأزمنة القيادة: يقارن زمن القيادة الفعلي بين المحطات (من AVL) بزمن السير الحر على شبكة الشوارع، فيخرج عامل ازدحام لكل فترة ولكل ضلع، ثم تُضرب به أزمنة القيادة في كل التحليلات."
    )
    w = U.ws()
    prof = w.obj("congestion")
    can_learn = U.get("avl") is not None and U.has_roads() and U.get("gtfs") is not None
    c1, c2 = st.columns(2)
    with c1:
        U.section("تعلّم من AVL")
        if not can_learn:
            st.info("يحتاج: AVL وGTFS وشوارع OSM (من صفحة البيانات).")
        prior = st.number_input(
            "انكماش الأضلاع قليلة المشاهدات (م مكافئة)",
            100,
            2000,
            400,
            100,
            key="hub_c_prior",
            help="كلما زاد، اقترب عامل الضلع قليل المشاهدات من العامل العام",
        )
        if st.button("تعلّم الازدحام", type="primary", disabled=not can_learn, key="hub_c_learn"):
            try:
                net = load_access(w, True, False).net
                p = CG.learn_from_avl(net, U.feed_obj(), P.clean_avl(U.get("avl")), U.proj(), float(prior))
                w.save_obj("congestion", p)
                w.set_source("congestion", "upload")
                w.log("congestion_learned", factors={k: round(v, 3) for k, v in p.period_factor.items()})
                st.cache_data.clear()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
    with c2:
        U.section("أو منحنى ساعات يدوي")
        st.caption("CSV بعمودي hour (0–23) وfactor (زمن الرحلة ÷ السير الحر). يطبّق عاماً على كل الشوارع.")
        up = st.file_uploader("منحنى الازدحام", type="csv", key="hub_c_up")
        if up is not None and st.button("اعتمد المنحنى", key="hub_c_ok"):
            try:
                import pandas as pd

                p = CG.from_hourly(pd.read_csv(up, encoding="utf-8-sig"))
                w.save_obj("congestion", p)
                w.set_source("congestion", "upload")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
    if prof is None:
        U.empty("لا ملف ازدحام بعد: الأزمنة بسرعات فئة الطريق × 0.8.")
        return
    acc = load_access(w, True, True)
    net_ok = acc.net is None or prof.compatible(acc.net)
    if not net_ok:
        st.warning("الازدحام المتعلَّم من شبكة شوارع مختلفة عن الحالية، لذلك لا يُطبَّق. أعد التعلّم.")
    U.section("عوامل الازدحام")
    tab = prof.table()
    U.kpis([(f"×{r.factor:.2f}", r.period, "hard" if r.factor >= 1.5 else "mid" if r.factor >= 1.2 else "ok") for r in tab.itertuples()])
    U.period_bars(tab, "period", "factor", "عامل الازدحام (1 = بلا ازدحام)")
    if prof.diagnostics is not None:
        U.table(prof.diagnostics)
    if prof.edge_obs is not None and acc.net is not None and net_ok:
        period = st.selectbox("الفترة", CG.PERIOD_KEYS, index=1, key="hub_c_period")
        wl = CG.worst_links(prof, acc.net, period, 200)
        if len(wl):
            proj = U.proj()
            wl["lon_a"], wl["lat_a"] = proj.lonlat(wl["xa"], wl["ya"])
            wl["lon_b"], wl["lat_b"] = proj.lonlat(wl["xb"], wl["yb"])
            lo, hi = wl["factor"].min(), wl["factor"].max()
            wl["color"] = [[int(255 * t), int(200 * (1 - t)), 40] for t in ((wl["factor"] - lo) / max(hi - lo, 1e-9)).clip(0, 1)]
            U.deck(
                [
                    pdk.Layer(
                        "LineLayer",
                        wl,
                        get_source_position="[lon_a, lat_a]",
                        get_target_position="[lon_b, lat_b]",
                        get_color="color",
                        get_width=5,
                        width_min_pixels=3,
                    )
                ]
            )
            U.legend([("أقل ازدحاماً بين المرصود", [0, 200, 40]), ("أكثر ازدحاماً", [255, 0, 40])])
            U.table(wl.head(15)[["factor", "length_m", "lon_a", "lat_a"]])
    if st.button("إزالة ملف الازدحام", key="hub_c_rm"):
        w.delete("congestion")
        st.cache_data.clear()
        st.rerun()


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
    tabs = st.tabs(["الالتزام بالمواعيد", "انتظام التردد", "الركاب", "الازدحام وأزمنة القيادة", "توصيات"])
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
        _congestion_tab()

    with tabs[4]:
        for r in P.recommend(otp if otp is not None else pd.DataFrame(columns=["route_id", "late_pct"]), rt, reg, apc_sum):
            st.markdown(f"- {r}")
