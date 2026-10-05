"""صفحة النقل العام: نظرة عامة، التغطية، الوصول بالزمن، التخطيط، الأسطول والتشغيل."""

import io

import pandas as pd
import streamlit as st

from transport_hub.admin import finance
from transport_hub.core import geo
from transport_hub.transit import coverage as COV
from transport_hub.transit import csa, planning, priority, ridership, service, timetable
from transport_hub.transit import gtfs as G
from transport_hub.ui import common as U


@st.cache_data(show_spinner="جاري حساب التغطية…")
def _cov(sig_, walk_radii):
    feed, proj = U.feed_obj(), U.proj()
    pop = U.get("population")
    st_ = COV.stops_frame(feed, proj)
    sr = service.stop_route_freq(feed)
    k, cov = planning.scenario_kpis(pop, st_, sr, radii=walk_radii, access=U.access())
    return k, cov, st_, sr


@st.cache_data(show_spinner=False)
def _routes(sig_):
    feed, proj = U.feed_obj(), U.proj()
    return service.route_metrics(feed, proj=proj, access=U.access()), service.headways(feed), service.hubs(feed, proj)


@st.cache_data(show_spinner="جاري فحص واقعية الجدول…")
def _rtc(sig_):
    return service.route_time_check(U.feed_obj(), U.proj(), U.access())


@st.cache_resource(show_spinner="جاري تجهيز محرك الرحلات…")
def _router(sig_):
    return csa.Router(U.feed_obj(), U.proj(), access=U.access())


def render():
    U.style()
    U.page_header(
        "النقل العام",
        "تغطية السكان، مستوى الخدمة، الوصول بالزمن، وتخطيط محطات وخطوط جديدة.",
        "**مؤشر الخدمة** (على طريقة PTAL) يجمع المشي والتردد: 1 ضعيف جداً … 6 ممتاز.  \n**الوصول بالزمن**: ماذا أبلغ خلال X دقيقة شاملاً المشي والتبديل.  \n المسافات مستقيمة × 1.3 (تقدير).",
    )
    U.access_bar()
    d = U.require("population", "gtfs", what="")
    if d is None:
        return
    feed, proj = U.feed_obj(), U.proj()
    sg = U.sig()
    k, cov, stops, sr = _cov(sg, (400, 800))
    rm, hw, hubs = _routes(sg)
    pop = d["population"]
    tabs = st.tabs(["نظرة عامة", "التغطية", "الوصول بالزمن", "التخطيط", "واقعية الجدول", "أولوية الحافلات", "الأسطول والتشغيل"])

    with tabs[0]:
        U.kpis(
            [
                (len(feed.routes), "خطوط"),
                (len(feed.stops), "محطات"),
                (int(rm["trips_per_day"].sum()), "رحلات/يوم"),
                (f"{k['covered_400_pct']:.0f}%", "تغطية 400 م", "ok" if k["covered_400_pct"] >= 60 else "hard"),
                (f"{k['covered_800_pct']:.0f}%", "تغطية 800 م", "ok" if k["covered_800_pct"] >= 85 else "mid"),
                (f"{k['avg_access_index']:.1f}", "متوسط مؤشر الخدمة"),
            ]
        )
        st.markdown("**مقاييس الخطوط**")
        U.table(
            rm.rename(
                columns={
                    "route_id": "الخط",
                    "name": "الاسم",
                    "stops": "محطات",
                    "length_km": "الطول كم",
                    "avg_stop_spacing_m": "تباعد المحطات م",
                    "run_time_min": "زمن الرحلة د",
                    "commercial_speed_kmh": "السرعة التجارية",
                    "trips_per_day": "رحلات/يوم",
                    "peak_headway_min": "تردد الذروة د",
                    "peak_fleet": "أسطول الذروة",
                    "service_span": "ساعات الخدمة",
                }
            )
        )
        pv = hw.pivot_table(index="route_id", columns="period", values="headway_min", aggfunc="mean").round(1).rename_axis(index="الخط", columns=None)
        st.markdown("**التردد (دقيقة) حسب الفترة**")
        st.dataframe(pv, width="stretch")
        st.markdown("**محاور التبديل**")
        U.table(hubs[["routes", "stops", "lon", "lat"]].rename(columns={"routes": "خطوط", "stops": "محطات"}).head(15))
        with st.expander("فحص جودة GTFS"):
            U.table(G.validate(feed))

    with tabs[1]:
        c = st.columns(3)
        mode = c[0].selectbox("التلوين", ["مؤشر مستوى الخدمة", "مغطى / غير مغطى (400 م)"], key="hub_t_cmode")
        show_stops = c[1].checkbox("إظهار المحطات", True, key="hub_t_stops")
        cv = cov.copy()
        cv["lon"], cv["lat"] = proj.lonlat(cv["x"], cv["y"])
        if mode.startswith("مؤشر"):

            def col(r):
                return U.GRADE_COL[str(r.grade)[0]]
        else:

            def col(r):
                return [46, 158, 79] if r.covered_400 else [209, 56, 61]

        layers = [U.scatter(cv, col, size_col=230, opacity=0.65)]
        if show_stops:
            s2 = stops.rename(columns={"stop_lon": "lon", "stop_lat": "lat"})
            layers.append(U.scatter(s2, [20, 20, 20], size_col=45, opacity=0.9))
        U.deck(layers)
        st.markdown("**ملخص التغطية حسب الحي**")
        U.table(COV.summary(cv))

    with tabs[2]:
        st.caption("نموذج رحلات زمني (Connection Scan): من أين تصل خلال X دقيقة بالنقل العام شاملاً المشي والتبديل.")
        c = st.columns(3)
        zone = c[0].selectbox("منطقة الانطلاق", pop["name"].tolist(), key="hub_t_origin")
        hour = c[1].slider("ساعة الانطلاق", 5.0, 22.0, 8.0, 0.5, key="hub_t_hour")
        mins = c[2].slider("الحد الأقصى للرحلة (د)", 15, 90, 45, 5, key="hub_t_mins")
        o = pop[pop["name"] == zone].iloc[0]
        r = _router(sg)
        arr = r.earliest_arrival(o["x"], o["y"], hour * 3600, horizon_s=mins * 60 + 600)
        ok = r.reachable_points(arr, pop[["x", "y"]].to_numpy(), hour * 3600, mins)
        poi = U.get("poi")
        items = [
            (f"{int(pop.loc[ok, 'pop'].sum()):,}", "سكان يمكن بلوغهم"),
            (f"{100 * ok.mean():.0f}%", "من المناطق"),
            (f"{int(pop.loc[ok, 'jobs'].sum()):,}", "وظائف"),
        ]
        if poi is not None:
            pok = r.reachable_points(arr, poi[["x", "y"]].to_numpy(), hour * 3600, mins)
            items.append((f"{int(pok.sum())} / {len(poi)}", "نقاط جذب"))
        U.kpis(items)
        z = pop.copy()
        z["ok"] = ok
        U.deck(
            [
                U.scatter(z, lambda r_: [21, 101, 192] if r_.ok else [190, 190, 190], size_col=230, opacity=0.6),
                U.scatter(pop[pop["name"] == zone], [220, 30, 30], size_col=350),
            ]
        )

    with tabs[3]:
        poi = U.get("poi")
        sub = st.radio("الأداة", ["محطات جديدة", "اقتراح خط جديد", "تعديل الترددات"], horizontal=True, key="hub_t_plan")
        cell = st.select_slider("دقة المرشحين (م)", [150, 200, 250, 400], 250, key="hub_t_cell")
        cand = geo.candidate_grid(pop["x"], pop["y"], cell)
        ex = stops[["x", "y"]].to_numpy()
        if sub == "محطات جديدة":
            c = st.columns(3)
            kk = c[0].number_input("عدد المحطات", 1, 100, 10, key="hub_t_k")
            rad = c[1].number_input("مسافة المشي (م)", 200, 1000, 400, 50, key="hub_t_rad")
            pw = c[2].slider("وزن قرب نقاط الجذب", 0.0, 1.0, 0.2, 0.05, key="hub_t_pw")
            sel, (b, a) = planning.suggest_stops(pop, ex, cand, rad, int(kk), poi, pw, proj, U.access())
            U.kpis([(f"{b:.1f}% → {a:.1f}%", f"التغطية عند {rad} م"), (int(sel["gain"].sum()), "سكان جدد")])
            U.deck(
                [
                    U.scatter(pop.assign(lon=pop["lon"], lat=pop["lat"]), [160, 160, 160], size_col=200, opacity=0.4),
                    U.scatter(stops.rename(columns={"stop_lon": "lon", "stop_lat": "lat"}), [20, 20, 20], size_col=45),
                    U.scatter(sel, [230, 120, 0], size_col=120),
                ]
            )
            U.table(sel[["rank", "gain", "cum_covered_pct", "lon", "lat"]].round(3))
            U.download_df("تنزيل المواقع (CSV)", sel, "new_stops.csv", "hub_t_dl_stops")
        elif sub == "اقتراح خط جديد":
            c = st.columns(4)
            n = c[0].number_input("محطات الخط", 4, 40, 10, key="hub_t_ln")
            hwy = c[1].number_input("التردد (د)", 3, 60, 10, key="hub_t_lh")
            spd = c[2].number_input("السرعة التجارية كم/س", 10, 50, 20, key="hub_t_ls")
            rad = c[3].number_input("مسافة المشي (م)", 200, 1000, 400, 50, key="hub_t_lr")
            line, info = planning.suggest_line(
                pop, ex, hubs[["x", "y"]].to_numpy() if len(hubs) else None, cand, int(n), rad, hwy, spd, proj=proj, access=U.access()
            )
            if line.empty:
                U.empty("ما فيه مناطق غير مخدومة تستحق خطاً جديداً.")
            else:
                U.kpis(
                    [
                        (info["length_km"], "الطول كم"),
                        (info["run_time_min"], "زمن الرحلة د"),
                        (info["fleet"], "الأسطول المطلوب"),
                        (f"{info['pop_covered_new']:,}", "سكان جدد"),
                        (f"{info['coverage_before']}% → {info['coverage_after']}%", "التغطية"),
                    ]
                )
                bp = info["run_time_by_period"]
                st.caption(
                    "زمن الرحلة الواقعي حسب الفترة (شبكة + ازدحام): "
                    + "، ".join(f"{p} {t:.0f} د" for p, t in bp.items())
                    + f" · الأسطول الواقعي = {info['fleet_realistic']} (الأكبر عبر الفترات) مقابل {info['fleet']} بسرعة الإدخال."
                )
                import pydeck as pdk

                path = pdk.Layer(
                    "PathLayer", [{"path": line[["lon", "lat"]].values.tolist()}], get_path="path", width_min_pixels=4, get_color=[230, 120, 0]
                )
                U.deck(
                    [
                        U.scatter(stops.rename(columns={"stop_lon": "lon", "stop_lat": "lat"}), [20, 20, 20], size_col=45),
                        path,
                        U.scatter(line, [230, 120, 0], size_col=110),
                    ]
                )
                tb = timetable.build_line(
                    "NEW1", "خط مقترح", [(f"م{r_.order}", r_.lon, r_.lat) for r_ in line.itertuples()], speed_kmh=spd, periods=[(6, 22, hwy)]
                )
                merged = timetable.merge_tables(U.get("gtfs"), tb)
                buf = io.BytesIO()
                G.write_zip(merged, buf)
                st.download_button("تنزيل GTFS بعد إضافة الخط (zip)", buf.getvalue(), file_name="gtfs_with_new_line.zip", key="hub_t_dl_gtfs")
                if st.button("احفظ كسيناريو", key="hub_t_save_sc"):
                    from transport_hub.admin.scenarios import ScenarioBook

                    add = [dict(x=r_.x, y=r_.y, route_id="NEW1", headway_min=hwy) for r_ in line.itertuples()]
                    kk2, _ = planning.scenario_kpis(pop, stops, sr, add_stops=add, access=U.access())
                    ScenarioBook(U.ws()).save(f"خط جديد ({n} محطة، {hwy} د)", dict(info), kk2)
                    st.success("حُفظ في سجل السيناريوهات (صفحة الإدارة)")
        else:
            routes = rm["route_id"].tolist()
            sel_r = st.multiselect("الخطوط", routes, key="hub_t_hr")
            f = st.slider("معامل التردد (0.5 = ضعف الخدمة، 2 = نصفها)", 0.3, 3.0, 0.5, 0.1, key="hub_t_hf")
            k2, _ = planning.scenario_kpis(pop, stops, sr, headway_factor={r_: f for r_ in sel_r}, access=U.access())
            base = {**k}
            U.table(pd.DataFrame({"المؤشر": list(base), "الأساس": [float(v) for v in base.values()], "السيناريو": [float(v) for v in k2.values()]}))
            if st.button("احفظ كسيناريو", key="hub_t_save_hw"):
                from transport_hub.admin.scenarios import ScenarioBook

                ScenarioBook(U.ws()).save(f"تردد ×{f} على {len(sel_r)} خط", dict(factor=f, routes=sel_r), k2)
                st.success("حُفظ")

    with tabs[4]:
        rtc = _rtc(sg)
        if rtc.empty:
            U.empty("لا رحلات كافية لفحص واقعية الجدول.")
        else:
            short = rtc[rtc["verdict"].str.startswith("ناقص")]
            extra = int((rtc["fleet_needed"] - rtc["fleet_scheduled"]).clip(lower=0).groupby(rtc["route_id"]).max().sum())
            U.kpis(
                [
                    (f"{len(short)} / {len(rtc)}", "حالات الجدول فيها أقصر من الواقع", "hard" if len(short) else "ok"),
                    (extra, "مركبات إضافية للوفاء بالزمن الواقعي", "hard" if extra else "ok"),
                    (f"{rtc['delta_min'].max():.1f} د", "أكبر نقص في الزمن"),
                ]
            )
            if U.access().profile is None:
                st.info("الأزمنة المتوقعة بسرعات فئة الطريق. تعلّم الازدحام من AVL (صفحة «الأداء الفعلي» ← الازدحام) لأزمنة أدق حسب الفترة.")
            U.table(rtc.drop(columns=["name"]))
            st.caption(
                "المتوقع = قيادة بين المحطات على الشبكة بازدحام الفترة + توقفات الجدول. «ناقص» يعني أن الجدول أقصر من الواقع: تأخيرات مزمنة وحاجة لأسطول أكبر أو جدول أطول."
            )
            st.bar_chart(rtc.pivot_table(index="route_id", columns="period", values="delta_min").rename_axis("الخط"))

    with tabs[5]:
        st.caption("ماذا لو أُعطي الخط أولوية (ممر مخصص أو أولوية إشارات) على الأضلاع الأكثر تأخيراً في مساره؟")
        routes_ = rm["route_id"].tolist()
        c = st.columns(4)
        rid = c[0].selectbox("الخط", routes_, key="hub_t_prio_r")
        share = c[1].slider("حصة المسار بأولوية", 0.1, 1.0, 0.4, 0.05, key="hub_t_prio_s")
        cut = c[2].slider("تقليل التأخير على تلك الأضلاع", 0.2, 0.9, 0.6, 0.05, key="hub_t_prio_c")
        zz, _bs, br_ = ridership.estimate(cov, stops, sr)
        est_pax = float(br_.loc[br_["route_id"] == rid, "pax_day"].sum())
        pax = c[3].number_input("ركاب/يوم", 0, 10**7, int(est_pax), 500, key="hub_t_prio_p")
        res = priority.evaluate(feed, proj, U.access(), rid, share, cut, pax or None)
        sm = res["summary"]
        U.kpis(
            [
                (f"{sm['vehicle_hours_saved_year']:,.0f}", "ساعات مركبة موفّرة/سنة"),
                (f"{sm['opex_saving_year']:,.0f}", "وفر تشغيل/سنة (ريال)"),
                (sm["fleet_saved"], "مركبات موفّرة في الذروة"),
                (f"{sm.get('passenger_hours_saved_year', 0):,.0f}", "ساعات ركاب موفّرة/سنة"),
            ]
        )
        U.table(res["table"])
        if res["links"] is not None and len(res["links"]):
            lk = res["links"].copy()
            lk["lon_a"], lk["lat_a"] = proj.lonlat(lk["xa"], lk["ya"])
            lk["lon_b"], lk["lat_b"] = proj.lonlat(lk["xb"], lk["yb"])
            import pydeck as pdk

            U.deck(
                [
                    pdk.Layer(
                        "LineLayer",
                        lk,
                        get_source_position="[lon_a, lat_a]",
                        get_target_position="[lon_b, lat_b]",
                        get_color=[230, 120, 0],
                        get_width=6,
                        width_min_pixels=3,
                    )
                ]
            )
            U.legend([("أضلاع الأولوية المقترحة", [230, 120, 0])])
        st.caption("وقت الركاب مُقيَّم بـ 20 ريال/ساعة (قابل للتعديل في الكود)، وتكلفة التشغيل بأجر سائق وتكلفة وقود وصيانة تقديرية.")

    with tabs[6]:
        z, by_stop, by_route = ridership.estimate(cov, stops, sr)
        prod = ridership.productivity(by_route, rm)
        st.caption("الركاب تقدير أولي من نموذج حصة النقل العام (يحتاج معايرة بعدّادات الركاب أو مسح).")
        U.table(
            prod[["route_id", "name", "pax_day", "pax_per_km", "pax_per_vehicle_hour", "load_ratio", "peak_fleet"]]
            .round(1)
            .rename(
                columns={
                    "route_id": "الخط",
                    "name": "الاسم",
                    "pax_day": "ركاب/يوم",
                    "pax_per_km": "ركاب/كم",
                    "pax_per_vehicle_hour": "ركاب/ساعة مركبة",
                    "load_ratio": "نسبة التحميل",
                    "peak_fleet": "أسطول الذروة",
                }
            )
        )
        over = prod[prod["load_ratio"] > 1]
        if len(over):
            st.warning("خطوط الطلب المقدّر فيها يفوق السعة: " + "، ".join(over["route_id"]) + " (فكّر بزيادة التردد أو مركبات أكبر).")
        vt = st.selectbox("نوع المركبة للتكلفة", list(finance.DEFAULT_COSTS), key="hub_t_vt")
        rows = []
        for r_ in prod.itertuples():
            km_day = r_.length_km * r_.trips_per_day
            hrs = r_.run_time_min * r_.trips_per_day / 60
            c = finance.annual_cost(vt, int(r_.peak_fleet or 0), km_day, hrs)
            rows.append(
                dict(
                    الخط=r_.route_id,
                    الأسطول=int(r_.peak_fleet or 0),
                    التكلفة_السنوية=round(c["total"]),
                    تكلفة_الراكب=round(finance.cost_per_passenger(c["total"], r_.pax_day), 2) if r_.pax_day else None,
                    انبعاثات_طن=round(c["co2_t"], 1),
                )
            )
        U.table(pd.DataFrame(rows))
