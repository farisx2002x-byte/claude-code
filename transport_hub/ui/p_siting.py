"""صفحة اختيار المواقع: لأي منشأة (محطة، موقف، مستودع، شحن، مركز تجميع...) بثلاث طرق: معايير متعددة، أقصى تغطية، p-median."""

import streamlit as st

from transport_hub.core import geo
from transport_hub.siting import coverage as SC
from transport_hub.siting import mcda
from transport_hub.transit import coverage as COV
from transport_hub.ui import common as U


def render():
    U.style()
    U.page_header(
        "اختيار المواقع",
        "أفضل أماكن المحطات والمواقف والمستودعات ومراكز الشحن، بثلاث طرق.",
        "**معايير متعددة**: أوزان قابلة للتعديل لكل معيار.  \n**أقصى تغطية**: يعظّم السكان المخدومين ضمن نصف القطر.  \n**p-median**: يقلل المسافة للأقرب (مراكز/مستودعات).",
    )
    d = U.require("population")
    if d is None:
        return
    pop, poi, proj = d["population"], U.get("poi"), U.proj()
    feed = U.feed_obj()
    stops_df = COV.stops_frame(feed, proj) if feed else None
    hubs_xy = None
    if feed:
        from transport_hub.transit import service

        h = service.hubs(feed, proj)
        hubs_xy = h[["x", "y"]].to_numpy() if len(h) else stops_df[["x", "y"]].to_numpy()
    trips = U.get("trips")
    trips_xy = trips[["px", "py"]].to_numpy() if trips is not None else None

    c = st.columns(3)
    kind = c[0].selectbox("نوع المنشأة", list(mcda.PRESETS), key="hub_s_kind")
    method = c[1].selectbox("الطريقة", ["معايير متعددة (MCDA)", "أقصى تغطية", "p-median (مراكز/مستودعات)"], key="hub_s_method")
    cell = c[2].select_slider("دقة المرشحين (م)", [150, 200, 250, 400, 500], 250, key="hub_s_cell")
    cfg = mcda.PRESETS[kind]
    st.caption(cfg["desc"])
    cc = st.columns(3)
    n = cc[0].number_input("عدد المواقع", 1, 100, 10, key="hub_s_n")
    radius = cc[1].number_input("نصف قطر الخدمة (م)", 100, 5000, int(cfg["radius"]), 50, key="hub_s_r")
    spacing = cc[2].number_input("أدنى تباعد (م)", 0, 5000, int(cfg["spacing"]), 50, key="hub_s_sp")
    cand = geo.candidate_grid(pop["x"], pop["y"], cell)
    existing = None
    if kind == "محطة حافلات" and stops_df is not None:
        existing = stops_df[["x", "y"]].to_numpy()
    elif kind == "موقف تاكسي" and U.get("stands") is not None:
        existing = U.get("stands")[["x", "y"]].to_numpy()

    if method.startswith("معايير"):
        w = {}
        cols = st.columns(len(cfg["weights"]))
        labels = {
            "pop": "السكان",
            "gap": "فجوة الخدمة",
            "poi": "نقاط الجذب",
            "low_income": "محدودو الدخل",
            "hub": "القرب من محور",
            "trips": "كثافة الرحلات",
            "edge": "الأطراف",
            "students": "الطلاب",
        }
        for col, (k_, v) in zip(cols, cfg["weights"].items()):
            w[k_] = col.slider(labels.get(k_, k_), 0.0, 1.0, float(v), 0.05, key=f"hub_s_w_{k_}")
        scored, crit = mcda.evaluate_site_type(kind, cand, pop, poi, existing, hubs_xy, trips_xy, w, radius)
        mask = None
        if existing is not None and len(existing):
            mask = geo.nearest(cand[["x", "y"]].to_numpy(), existing)[0] >= spacing
        sel = mcda.pick(scored, int(n), spacing, mask)
        sel["lon"], sel["lat"] = proj.lonlat(sel["x"], sel["y"])
        sc = scored.copy()
        sc["lon"], sc["lat"] = proj.lonlat(sc["x"], sc["y"])
        U.kpis([(f"{sel['score'].max():.0f}", "أعلى درجة"), (f"{sel['score'].mean():.0f}", "متوسط المختار"), (len(crit), "معايير")])
        U.deck(
            [
                U.scatter(
                    sc,
                    lambda r: [int(255 * (1 - r.score / 100)), int(60 + 190 * r.score / 100), 80],
                    size_col=cell * 0.45,
                    opacity=0.35,
                    pickable=False,
                ),
                U.scatter(sel, [230, 120, 0], size_col=cell * 0.7),
            ]
        )
        show = ["rank", "score"] + [f"raw_{c_.name}" for c_ in crit] + ["lon", "lat"]
        U.table(sel[show].round(2))
    elif method == "أقصى تغطية":
        dxy = pop[["x", "y"]].to_numpy()
        sel, (b, a) = SC.max_coverage(dxy, pop["pop"].to_numpy(float), cand[["x", "y"]].to_numpy(), radius / geo.DETOUR, int(n), existing)
        sel["lon"], sel["lat"] = proj.lonlat(sel["x"], sel["y"])
        U.kpis([(f"{b:.1f}% → {a:.1f}%", "السكان المغطون"), (int(sel["gain"].sum()), "سكان جدد")])
        U.deck([U.scatter(pop, [160, 160, 160], size_col=200, opacity=0.4), U.scatter(sel, [230, 120, 0], size_col=cell * 0.7)])
        U.table(sel[["rank", "gain", "cum_covered_pct", "lon", "lat"]].round(2))
    else:
        w_col = "students" if kind == "مركز تجميع مدرسي" else "pop"
        sites, assign, cost = SC.p_median(pop[["x", "y"]].to_numpy(), pop[w_col].to_numpy(float), cand[["x", "y"]].to_numpy(), int(n))
        sites["lon"], sites["lat"] = proj.lonlat(sites["x"], sites["y"])
        U.kpis([(f"{cost / pop[w_col].sum() / 1000:.2f} كم", "متوسط المسافة للأقرب (مستقيم)"), (len(sites), "مواقع")])
        U.deck([U.scatter(pop, [160, 160, 160], size_col=200, opacity=0.4), U.scatter(sites, [230, 120, 0], size_col=cell * 0.9)])
        U.table(sites[["load", "lon", "lat"]].round(1).rename(columns={"load": "الحمل (سكان)"}))
    U.download_df("تنزيل المواقع (CSV)", sel if not method.startswith("p-") else sites, "sites.csv", "hub_s_dl")
