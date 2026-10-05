"""صفحة الإدارة: بطاقة المؤشرات، العدالة، السيناريوهات، التمويل والمشاريع، التقارير، وسجل التدقيق."""

import io
import pickle
from pathlib import Path

import pandas as pd
import streamlit as st

from transport_hub.admin import equity, finance, reports, scorecard
from transport_hub.admin.scenarios import ScenarioBook
from transport_hub.taxi import fleet as tfleet
from transport_hub.taxi import stands as tstands
from transport_hub.transit import coverage as COV
from transport_hub.transit import service
from transport_hub.ui import common as U

SCHOOL_PICKLE = Path(__file__).resolve().parents[2] / "bus_access_project" / "work" / "res_scored.pkl"
SCHOOL_ROUTES = Path(__file__).resolve().parents[2] / "bus_access_project" / "work" / "routes.pkl"


def _school_kpis():
    try:
        S = pickle.loads(SCHOOL_PICKLE.read_bytes())
        df = S["df"]
        out = {"school_hard": 100 * float((df["level_L"] == "صعب").mean())}
        if SCHOOL_ROUTES.exists():
            R = pickle.loads(SCHOOL_ROUTES.read_bytes())
            out["school_nopath"] = 100 * len(R["nores"]) / max(len(df), 1)
        return out
    except Exception:
        return {}


@st.cache_data(show_spinner="جاري حساب مؤشرات المنصة…")
def collect(sig_):
    """يجمع مؤشرات كل الوحدات المتاحة في dict واحد + جداول داعمة."""
    vals, tables = {}, {}
    feed = U.feed_obj()
    pop = U.get("population")
    proj = U.proj()
    if feed is not None and pop is not None:
        from transport_hub.transit import planning

        st_ = COV.stops_frame(feed, proj)
        sr = service.stop_route_freq(feed)
        acc = U.access()
        k, cov = planning.scenario_kpis(pop, st_, sr, access=acc)
        rm = service.route_metrics(feed, proj=proj, access=acc)
        vals.update(
            transit_cov400=k["covered_400_pct"],
            transit_cov800=k["covered_800_pct"],
            transit_ai=k["avg_access_index"],
            transit_headway=float(rm["peak_headway_min"].mean()),
            transit_no_service=100 * k["pop_no_service"] / pop["pop"].sum(),
            equity_gini=equity.gini(cov["access_index"], cov["pop"]),
        )
        tables.update(cov=cov, route_metrics=rm, districts=equity.by_district(cov), priority=equity.priority_zones(cov, 20))
    trips = U.get("trips")
    if trips is not None:
        k = tfleet.kpis(trips)
        if "متوسط الانتظار د" in k:
            vals["taxi_wait"] = k["متوسط الانتظار د"]
        if "نسبة الإشغال (وقت الرحلات)" in k:
            vals["taxi_util"] = 100 * k["نسبة الإشغال (وقت الرحلات)"]
        st_df = U.get("stands")
        if st_df is not None:
            vals["taxi_stand_cov"] = tstands.stand_coverage(trips, st_df[["x", "y"]].to_numpy(), 300, U.access())
        tables["taxi_kpis"] = pd.DataFrame({"المؤشر": list(k), "القيمة": list(k.values())})
    avl, apc, reg = U.get("avl"), U.get("apc"), U.get("register")
    if avl is not None:
        from transport_hub.ops import performance as P

        a = P.clean_avl(avl)
        vals["ops_otp"] = 100 * float(1 - (a["delay_s"] > P.LATE_S).mean() - (a["delay_s"] < -P.EARLY_S).mean())
        _, r = P.headway_regularity(a)
        if len(r):
            vals["ops_ewt"] = float(r["ewt_min"].mean())
    if apc is not None:
        from transport_hub.ops import performance as P

        s_ = P.apc_summary(P.clean_apc(apc), 72)
        vals["ops_crowded"] = float(s_["crowded_trips_pct"].mean())
    if reg is not None:
        from transport_hub.ops import fleetmgmt as F

        m = F.maintenance(F.clean_register(reg), 200)
        vals["fleet_overdue"] = 100 * float((m["status"] == "متأخرة").mean())
    vals.update(_school_kpis())
    return vals, tables


def render():
    U.style()
    U.page_header(
        "الإدارة",
        "مؤشرات الأداء مقابل المستهدفات، العدالة المكانية، السيناريوهات، والتمويل والتقارير.",
        "**بطاقة المؤشرات**: 🟢 محقق، 🟡 ضمن 15% من المستهدف، 🔴 متأخر. المستهدفات قابلة للتعديل.  \n**العدالة**: Gini يقيس تفاوت الخدمة بين السكان (0 = تساوٍ تام).  \n**السيناريوهات** تُحفظ من صفحة النقل العام (التخطيط).",
    )
    if U.get("population") is None and U.get("trips") is None:
        U.empty("أضف بيانات من صفحة «البيانات» لعرض مؤشرات الإدارة.")
        return
    vals, tables = collect(U.sig())
    ws = U.ws()
    tabs = st.tabs(["بطاقة المؤشرات", "العدالة", "السيناريوهات", "التمويل والمشاريع", "التقارير", "سجل التدقيق"])

    with tabs[0]:
        with st.expander("تعديل المستهدفات"):
            tg = {}
            cols = st.columns(3)
            for i, (key, title, unit, t, _d) in enumerate(scorecard.KPIS):
                tg[key] = cols[i % 3].number_input(f"{title} ({unit})" if unit else title, value=float(t), key=f"hub_ad_t_{key}")
        sc = scorecard.build(vals, tg)
        g = (sc["الحالة"] == "🟢").sum()
        r = (sc["الحالة"] == "🔴").sum()
        U.kpis(
            [
                (g, "مؤشرات محققة", "ok"),
                (int((sc["الحالة"] == "🟡").sum()), "قريبة", "mid"),
                (r, "متأخرة", "hard"),
                (int((sc["الحالة"] == "غير متوفر").sum()), "بدون بيانات"),
            ]
        )
        U.table(sc.drop(columns="key"))
        if not any(k_.startswith("school") for k_ in vals):
            st.caption("مؤشرات النقل المدرسي تظهر بعد تشغيل وحدة النقل المدرسي.")

    with tabs[1]:
        if "districts" not in tables:
            U.empty("العدالة تحتاج بيانات السكان وGTFS.")
        else:
            cov = tables["cov"]
            U.kpis([(f"{vals['equity_gini']:.2f}", "Gini لمؤشر الخدمة (0 = تساوٍ)", "ok" if vals["equity_gini"] < 0.35 else "hard")])
            c1, c2 = st.columns(2)
            c1.markdown("**الأحياء الأقل خدمة**")
            c1.dataframe(tables["districts"].head(10), width="stretch", hide_index=True)
            lz = equity.lorenz(cov["access_index"], cov["pop"])
            c2.markdown("**منحنى لورنز (الخدمة مقابل السكان)**")
            c2.line_chart(lz.rename(columns={"share_service": "حصة الخدمة"}).set_index("share_pop").rename_axis("حصة السكان"))
            st.markdown("**مناطق الأولوية للتدخل** (سكان × نقص الخدمة × محدودو الدخل)")
            U.table(tables["priority"].round(2))

    with tabs[2]:
        book = ScenarioBook(ws)
        cmp = book.compare()
        if cmp.empty:
            U.empty("ما فيه سيناريوهات محفوظة. من صفحة النقل العام (التخطيط) احفظ سيناريو ليظهر هنا.")
        else:
            st.dataframe(cmp.round(2), width="stretch")
            name = st.selectbox("حذف سيناريو", [""] + list(book.data), key="hub_ad_del")
            if name and st.button("حذف", key="hub_ad_delb"):
                book.delete(name)
                st.rerun()

    with tabs[3]:
        st.caption("نموذج تكلفة تقديري: قيم افتراضية قابلة للتعديل، لحساب مشاريع مرشحة وترتيبها تحت ميزانية محددة.")
        st.markdown("**ترتيب المشاريع تحت ميزانية**")
        base = pd.DataFrame(
            {
                "name": ["خط جديد 1", "تحسين تردد R1", "محطات جديدة", "مواقف تاكسي", "مركز تجميع مدرسي"],
                "cost": [4_000_000, 1_500_000, 600_000, 250_000, 900_000],
                "benefit": [80_000, 25_000, 30_000, 12_000, 8_000],
            }
        )
        proj_df = st.data_editor(
            base,
            num_rows="dynamic",
            key="hub_ad_projects",
            width="stretch",
            hide_index=True,
            column_config={"name": "المشروع", "cost": "التكلفة (ريال)", "benefit": "الفائدة (مثل: سكان مخدومون)"},
        )
        budget = st.number_input("الميزانية (ريال)", 0, 10**10, 5_000_000, 100_000, key="hub_ad_budget")
        if len(proj_df.dropna()):
            ch, rest = finance.prioritize(proj_df.dropna(), budget)
            U.kpis([(len(ch), "مشاريع مختارة", "ok"), (f"{int(ch['cost'].sum()):,}", "التكلفة"), (f"{int(ch['benefit'].sum()):,}", "الفائدة")])
            c1, c2 = st.columns(2)
            c1.markdown("**المختارة**")
            c1.dataframe(ch, hide_index=True, width="stretch")
            c2.markdown("**غير المختارة**")
            c2.dataframe(rest, hide_index=True, width="stretch")
        st.markdown("**تكلفة تشغيل أسطول**")
        c = st.columns(5)
        vt = c[0].selectbox("المركبة", list(finance.DEFAULT_COSTS), key="hub_ad_vt")
        nv = c[1].number_input("العدد", 1, 100000, 50, key="hub_ad_nv")
        km = c[2].number_input("كم/يوم للمركبة", 10, 1000, 200, key="hub_ad_km")
        hr = c[3].number_input("ساعات/يوم للمركبة", 1, 24, 10, key="hub_ad_hr")
        pax = c[4].number_input("ركاب/يوم (الأسطول)", 1, 10**7, 20000, key="hub_ad_pax")
        cst = finance.annual_cost(vt, nv, km * nv, hr * nv)
        U.kpis(
            [
                (f"{cst['total']:,.0f}", "التكلفة السنوية"),
                (f"{finance.cost_per_passenger(cst['total'], pax):.2f}", "تكلفة الراكب (ريال)"),
                (f"{cst['co2_t']:,.0f}", "CO₂ طن/سنة"),
            ]
        )

    with tabs[4]:
        sc = scorecard.build(vals)
        sheets = {"المؤشرات": sc.drop(columns="key")}
        for key, title in (("route_metrics", "مقاييس الخطوط"), ("districts", "الأحياء"), ("priority", "مناطق الأولوية"), ("taxi_kpis", "التاكسي")):
            if key in tables:
                sheets[title] = tables[key]
        cmp = ScenarioBook(ws).compare()
        if not cmp.empty:
            sheets["السيناريوهات"] = cmp.reset_index().rename(columns={"index": "السيناريو"})
        buf = io.BytesIO()
        reports.excel(buf, sheets)
        st.download_button("تقرير Excel", buf.getvalue(), file_name="تقرير_المنصة.xlsx", key="hub_ad_xl")
        st.download_button(
            "ملخص تنفيذي (HTML)",
            reports.executive_html("ملخص أداء منظومة النقل", sc).encode("utf-8"),
            file_name="ملخص_تنفيذي.html",
            key="hub_ad_html",
        )

    with tabs[5]:
        a = ws.audit()
        if len(a):
            U.table(a)
        else:
            U.empty("لا أحداث مسجلة.")
