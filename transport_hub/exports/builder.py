"""يجمع نتائج المنصة (من مساحة العمل) في أوراق Excel وأقسام تقرير وجداول GIS. بدون اعتماد على Streamlit."""

import numpy as np
import pandas as pd

from transport_hub.core import geo
from transport_hub.core.store import Workspace
from transport_hub.exports import meta as META
from transport_hub.exports.excel import Sheet


def _get(ws, name):
    d = ws.df(name)
    return d if d is not None else ws.obj(name)


def available(ws):
    return {k: ws.has(k) for k in ("population", "poi", "gtfs", "trips", "stands", "avl", "apc", "register")}


def assemble(ws: Workspace | None = None, radius=400, k_new=10, k_stands=8, wait_target=5.0):
    """يرجع (meta, sheets, sections, geo_tables). يتخطى الوحدات التي بياناتها غير متوفرة ويذكرها في ملاحظات الغلاف."""
    from transport_hub.admin import equity, scorecard
    from transport_hub.taxi import demand as TD
    from transport_hub.taxi import fleet as TF
    from transport_hub.taxi import stands as TS
    from transport_hub.transit import coverage as COV
    from transport_hub.transit import gtfs as G
    from transport_hub.transit import planning, ridership, service

    ws = ws or Workspace()
    have = available(ws)
    meta_idx = ws.meta()
    datasets = {
        k: {"rows": (len(_get(ws, k)) if k not in ("gtfs",) else len(_get(ws, k)["stops"])), "loaded": meta_idx.get(k, "")}
        for k, v in have.items()
        if v
    }
    params = {"نصف قطر المشي (م)": radius, "محطات جديدة مقترحة": k_new, "مواقف تاكسي مقترحة": k_stands, "انتظار التاكسي المستهدف (د)": wait_target}
    notes, sheets, sections, geo_tables = [], [], [], {}
    vals = {}
    pop = _get(ws, "population") if have["population"] else None
    proj = geo.Projector(ws.obj("proj_epsg")) if ws.obj("proj_epsg") else None

    if have["gtfs"] and pop is not None:
        feed = G.from_tables(_get(ws, "gtfs"))
        st = COV.stops_frame(feed, proj)
        sr = service.stop_route_freq(feed)
        k, cov = planning.scenario_kpis(pop, st, sr, radii=tuple(sorted({400, 800, int(radius)})))
        rm = service.route_metrics(feed, proj=proj)
        _, _, br = ridership.estimate(cov, st, sr)
        prod = ridership.productivity(br, rm)
        hubs = service.hubs(feed, proj)
        dist = equity.by_district(cov)
        pri = equity.priority_zones(cov, 20)
        g = equity.gini(cov["access_index"], cov["pop"])
        vals.update(
            transit_cov400=k["covered_400_pct"],
            transit_cov800=k["covered_800_pct"],
            transit_ai=k["avg_access_index"],
            transit_headway=float(rm["peak_headway_min"].mean()),
            transit_no_service=100 * k["pop_no_service"] / pop["pop"].sum(),
            equity_gini=g,
        )
        cand = geo.candidate_grid(pop["x"], pop["y"], 250)
        sel, (b, a) = planning.suggest_stops(pop, st[["x", "y"]].to_numpy(), cand, radius, k_new, _get(ws, "poi") if have["poi"] else None, 0.2, proj)
        geo_tables["محطات_مقترحة"] = sel[["rank", "gain", "cum_covered_pct", "lon", "lat"]]
        cv = proj.attach_lonlat(cov)
        grade_groups = []
        palette = {"0": "#999999", "1": "#d73027", "2": "#fc8d59", "3": "#fee08b", "4": "#a6d96a", "5": "#66bd63", "6": "#1a9850"}
        for gk, gdf in cv.groupby(cv["grade"].str[0]):
            grade_groups.append(dict(name=f"درجة {gk}", x=gdf["x"], y=gdf["y"], color=palette[gk], r=5, alpha=0.7))
        grade_groups.append(dict(name="محطات", x=st["x"], y=st["y"], color="#000", r=2.5))
        grade_groups.append(dict(name="مقترحة", x=sel["x"], y=sel["y"], color="#ff7f0e", r=6, alpha=1))
        sheets += [
            Sheet(
                "النقل العام - الخطوط",
                rm,
                "مقاييس الخطوط",
                ["السرعة التجارية = الطول ÷ زمن الرحلة. أسطول الذروة = زمن الدورة ÷ التردد."],
                chart={"type": "bar", "x": "route_id", "y": ["peak_fleet"], "title": "أسطول الذروة لكل خط"},
            ),
            Sheet(
                "النقل العام - الإنتاجية",
                prod[["route_id", "pax_day", "load_ratio", "peak_fleet"]],
                "الإنتاجية (تقدير)",
                ["الركاب تقدير أولي: يحتاج معايرة بعدّادات الركاب."],
            ),
            Sheet("التغطية حسب الحي", dist, "العدالة المكانية حسب الحي", [f"Gini لمؤشر الخدمة = {g:.2f} (0 = تساوٍ)"]),
            Sheet("مناطق الأولوية", pri, "مناطق الأولوية للتدخل"),
            Sheet(
                "محطات مقترحة",
                sel[["rank", "gain", "cum_covered_pct", "lon", "lat"]],
                f"محطات جديدة مقترحة ({radius} م)",
                [f"التغطية: {b:.1f}% ← {a:.1f}%"],
            ),
            Sheet("محاور التبديل", hubs[["routes", "stops", "lon", "lat"]].rename(columns={"routes": "trips"}), "محاور التبديل"),
        ]
        sections.append(
            dict(
                title="النقل العام",
                kpis=[
                    (f"{k[f'covered_{int(radius)}_pct']:.0f}%", f"تغطية {int(radius)} م", "ok" if k[f"covered_{int(radius)}_pct"] >= 60 else "bad"),
                    (f"{k['covered_800_pct']:.0f}%", "تغطية 800 م"),
                    (f"{k['avg_access_index']:.1f}", "متوسط مؤشر الخدمة"),
                    (len(feed.routes), "خطوط"),
                    (len(feed.stops), "محطات"),
                    (f"{g:.2f}", "Gini"),
                ],
                bars=(list(rm["route_id"]), list(rm["peak_fleet"].fillna(0)), "أسطول الذروة لكل خط"),
                table=rm,
                map=dict(groups=grade_groups, title="درجة الخدمة للمناطق والمحطات"),
                notes=[f"المحطات المقترحة ترفع التغطية من {b:.1f}% إلى {a:.1f}%."],
                page_break=True,
            )
        )
        sections.append(
            dict(
                title="العدالة المكانية ومناطق الأولوية",
                table=dist.head(12),
                notes=["الأحياء مرتبة من الأقل خدمة."],
                intro="أولوية التدخل = السكان × نقص الخدمة × (1 + محدودو الدخل).",
            )
        )
    else:
        notes.append("النقل العام: يحتاج السكان وGTFS.")

    if have["trips"]:
        trips = _get(ws, "trips")
        kp = TF.kpis(trips)
        hs = TD.hotspots(trips, 400, 0.5, None, proj)
        fh = TF.fleet_by_hour(trips, wait_target, 6.0, 0.75)
        ex = _get(ws, "stands")[["x", "y"]].to_numpy() if have["stands"] else np.zeros((0, 2))
        sel2, (b2, a2) = TS.suggest_stands(trips, ex, k_stands, 300, proj=proj)
        geo_tables["نقاط_ساخنة_تاكسي"] = hs[["rank", "trips_per_day", "share_pct", "peak_hour", "lon", "lat"]]
        geo_tables["مواقف_مقترحة"] = sel2[["rank", "trips_per_day", "cum_covered_pct", "lon", "lat"]]
        if "متوسط الانتظار د" in kp:
            vals["taxi_wait"] = kp["متوسط الانتظار د"]
        if "نسبة الإشغال (وقت الرحلات)" in kp:
            vals["taxi_util"] = 100 * kp["نسبة الإشغال (وقت الرحلات)"]
        vals["taxi_stand_cov"] = TS.stand_coverage(trips, ex, 300)
        sheets += [
            Sheet("التاكسي - مؤشرات", pd.DataFrame({"المؤشر": list(kp), "القيمة": list(kp.values())}), "مؤشرات التاكسي"),
            Sheet("التاكسي - نقاط ساخنة", hs[["rank", "trips_per_day", "share_pct", "peak_hour", "cells", "lon", "lat"]], "النقاط الساخنة للطلب"),
            Sheet(
                "التاكسي - الأسطول بالساعة",
                fh.rename(
                    columns={
                        "hour": "الساعة",
                        "trips": "الرحلات/ساعة",
                        "needed_wait": "حسب الانتظار",
                        "needed_util": "حسب الإشغال",
                        "needed": "المطلوب",
                    }
                ),
                f"المركبات المطلوبة لانتظار ≤ {wait_target:g} د",
                chart={"type": "bar", "x": "الساعة", "y": ["المطلوب"], "title": "المركبات المطلوبة حسب الساعة"},
            ),
            Sheet(
                "مواقف تاكسي مقترحة",
                sel2[["rank", "trips_per_day", "cum_covered_pct", "lon", "lat"]],
                "مواقف مقترحة",
                [f"التغطية: {b2:.1f}% ← {a2:.1f}%"],
            ),
        ]
        sections.append(
            dict(
                title="التاكسي",
                kpis=[(v, n) for n, v in list(kp.items())[:6]],
                bars=([f"{h}" for h in fh["hour"]], list(fh["needed"]), "المركبات المطلوبة حسب الساعة"),
                table=hs.head(10),
                page_break=True,
                notes=[f"مواقف مقترحة ترفع تغطية الالتقاط من {b2:.0f}% إلى {a2:.0f}%.", "العرض مقدّر من التوصيلات إن لم تتوفر مواقع المركبات."],
            )
        )
    else:
        notes.append("التاكسي: يحتاج رحلات التاكسي.")

    if have["gtfs"] and proj is not None:
        from transport_hub.ops import blocking as B

        feed = G.from_tables(_get(ws, "gtfs"))
        blocks, bs = B.build_blocks(B.trip_endpoints(feed, proj))
        duty, ds = B.duties(blocks)
        vt = B.vehicle_table(blocks)
        sheets += [
            Sheet("جدولة المركبات", vt, "المركبات المطلوبة وجداولها", [f"{bs['vehicles']} مركبة مقابل حد نظري {bs['theoretical_min']}."]),
            Sheet("قطع السائقين", duty, "قطع عمل السائقين", [f"أقل عدد سائقين تقريباً: {ds.get('min_drivers', '—')} (تقدير، ليس جدول ورديات)"]),
        ]
        sections.append(
            dict(
                title="التشغيل والجدولة",
                kpis=[
                    (bs["vehicles"], "مركبات مطلوبة"),
                    (bs["theoretical_min"], "الحد النظري"),
                    (f"{bs['utilization'] * 100:.0f}%", "الاستخدام"),
                    (ds.get("min_drivers", "—"), "سائقون (تقريبي)"),
                ],
                table=vt.head(15),
                page_break=True,
            )
        )

    if have["avl"]:
        from transport_hub.ops import performance as P

        a = P.clean_avl(_get(ws, "avl"))
        otp = P.on_time(a)
        _, reg = P.headway_regularity(a)
        rt = P.running_time(a, G.from_tables(_get(ws, "gtfs"))) if have["gtfs"] else None
        vals["ops_otp"] = 100 * float(1 - (a["delay_s"] > P.LATE_S).mean() - (a["delay_s"] < -P.EARLY_S).mean())
        if len(reg):
            vals["ops_ewt"] = float(reg["ewt_min"].mean())
        sheets.append(
            Sheet(
                "الأداء - الالتزام", otp, "الالتزام بالمواعيد", chart={"type": "bar", "x": "route_id", "y": ["on_time_pct"], "title": "% في الموعد"}
            )
        )
        if len(reg):
            sheets.append(Sheet("الأداء - الانتظام", reg, "انتظام التردد"))
        sections.append(
            dict(
                title="الأداء الفعلي",
                kpis=[(f"{vals['ops_otp']:.0f}%", "في الموعد", "ok" if vals["ops_otp"] >= 85 else "bad")],
                bars=(list(otp["route_id"]), list(otp["on_time_pct"]), "% في الموعد"),
                table=otp,
                notes=P.recommend(otp, rt, reg),
                page_break=True,
            )
        )

    if vals:
        sc_all = scorecard.build(vals)
        sc = sc_all[sc_all["الحالة"] != "غير متوفر"].copy()
        sc[["الفعلي", "الفرق"]] = sc[["الفعلي", "الفرق"]].round(1)
        n_na = len(sc_all) - len(sc)
        if n_na:
            notes.append(f"{n_na} مؤشرات بدون بيانات لم تُعرض (تظهر عند توفر مصادرها).")
        sheets.insert(
            0,
            Sheet(
                "بطاقة المؤشرات",
                sc.drop(columns="key"),
                "بطاقة مؤشرات الأداء",
                ["🟢 محقق · 🟡 ضمن 15% من المستهدف · 🔴 متأخر"],
                status_cols=["الحالة"],
            ),
        )
        sections.insert(
            0,
            dict(
                title="بطاقة المؤشرات",
                kpis=[
                    ((sc["الحالة"] == "🟢").sum(), "محققة", "ok"),
                    ((sc["الحالة"] == "🟡").sum(), "قريبة", "mid"),
                    ((sc["الحالة"] == "🔴").sum(), "متأخرة", "bad"),
                ],
                table=sc.drop(columns="key"),
            ),
        )
    meta = META.build("تقرير أداء منظومة النقل", params, datasets, notes, demo=ws.is_demo())
    return meta, sheets, sections, geo_tables


def build_package(ws=None, **kw):
    from transport_hub.exports import package

    meta, sheets, sections, geo_tables = assemble(ws, **kw)
    if not sheets:
        raise ValueError("لا بيانات كافية لبناء مخرجات: أضف السكان وGTFS أو رحلات التاكسي")
    return package.build_zip(meta, sheets, sections, geo_tables), meta
