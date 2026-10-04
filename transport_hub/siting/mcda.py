"""تحليل متعدد المعايير لاختيار مكان أي منشأة: معايير بأوزان، تطبيع، قيود مسافة، وترتيب المواقع."""
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from transport_hub.core import geo


@dataclass
class Criterion:
    name: str
    values: np.ndarray       # قيمة لكل مرشح
    weight: float
    benefit: bool = True     # True: الأكبر أفضل، False: الأصغر أفضل
    note: str = ""


def _norm(v, benefit):
    v = np.asarray(v, float)
    lo, hi = np.nanmin(v), np.nanmax(v)
    n = np.zeros_like(v) if hi - lo < 1e-12 else (v - lo) / (hi - lo)
    return n if benefit else 1 - n


# ───── بناة المعايير (كل واحد يرجع قيمة لكل مرشح) ─────
def pop_within(cand_xy, pop_df, radius, col="pop"):
    tree = cKDTree(pop_df[["x", "y"]].to_numpy())
    w = pop_df[col].to_numpy(float)
    return np.array([w[l].sum() for l in tree.query_ball_point(cand_xy, radius)])


def poi_within(cand_xy, poi_df, radius, categories=None):
    p = poi_df if categories is None else poi_df[poi_df["category"].isin(categories)]
    if len(p) == 0:
        return np.zeros(len(cand_xy))
    tree = cKDTree(p[["x", "y"]].to_numpy())
    w = p["weight"].to_numpy(float)
    return np.array([w[l].sum() for l in tree.query_ball_point(cand_xy, radius)])


def dist_to(cand_xy, pts_xy):
    d, _ = geo.nearest(cand_xy, np.asarray(pts_xy, float))
    return d


def uncovered_pop(cand_xy, pop_df, existing_xy, radius, col="pop"):
    """السكان غير المغطين حالياً ضمن radius من المرشح (فجوة الخدمة)."""
    d, _ = geo.nearest(pop_df[["x", "y"]].to_numpy(), np.asarray(existing_xy, float)) if existing_xy is not None and len(existing_xy) else (np.full(len(pop_df), np.inf), None)
    unc = pop_df[d * geo.DETOUR > radius]
    return pop_within(cand_xy, unc, radius, col) if len(unc) else np.zeros(len(cand_xy))


def score(cand, criteria):
    """يضيف عمود لكل معيار (مطبّع 0–1) والدرجة الكلية 0–100."""
    out = cand.copy()
    tw = sum(c.weight for c in criteria) or 1.0
    total = np.zeros(len(out))
    for c in criteria:
        out[f"raw_{c.name}"] = c.values
        out[f"n_{c.name}"] = _norm(c.values, c.benefit)
        total += c.weight / tw * out[f"n_{c.name}"]
    out["score"] = 100 * total
    return out


def pick(scored, top=10, min_spacing_m=0.0, mask=None):
    """أفضل المواقع مع حد أدنى للتباعد بينها، ومع قناع قيود اختياري (True = مسموح)."""
    s = scored if mask is None else scored[mask]
    s = s.sort_values("score", ascending=False)
    chosen = []
    for i, r in s.iterrows():
        if all(np.hypot(r["x"] - scored.at[j, "x"], r["y"] - scored.at[j, "y"]) >= min_spacing_m for j in chosen):
            chosen.append(i)
            if len(chosen) >= top:
                break
    res = scored.loc[chosen].copy()
    res.insert(0, "rank", np.arange(1, len(res) + 1))
    return res


# ───── قوالب أنواع المنشآت: أوزان وإعدادات ─────
PRESETS = {
    "محطة حافلات": dict(radius=400, spacing=350, weights=dict(pop=0.35, gap=0.30, poi=0.20, low_income=0.10, hub=0.05),
                        desc="تغطية سكان غير مخدومين قرب نقاط الجذب."),
    "موقف تاكسي": dict(radius=300, spacing=500, weights=dict(poi=0.40, pop=0.15, hub=0.30, trips=0.15),
                       desc="قرب نقاط الجذب ومحاور النقل وكثافة الالتقاط التاريخية."),
    "موقف انتظار وركوب (Park & Ride)": dict(radius=1500, spacing=2000, weights=dict(pop=0.25, hub=0.35, gap=0.10, poi=0.10, edge=0.20),
                                           desc="عند أطراف المدينة قرب محور نقل رئيسي."),
    "مستودع حافلات": dict(radius=3000, spacing=3000, weights=dict(pop=0.30, edge=0.35, hub=0.20, poi=0.15),
                          desc="يقلل الرحلات الفارغة؛ يفضّل الأطراف القريبة من الخطوط."),
    "محطة شحن كهربائي": dict(radius=500, spacing=800, weights=dict(poi=0.35, trips=0.30, hub=0.20, pop=0.15),
                             desc="قرب مواقع الوقوف الطويل ومراكز النشاط."),
    "مركز تجميع مدرسي": dict(radius=600, spacing=600, weights=dict(students=0.55, gap=0.25, hub=0.10, pop=0.10),
                             desc="يخدم أكبر عدد طلاب بعيدين عن الباص."),
}


def evaluate_site_type(kind, cand, pop, poi, existing_xy=None, hubs_xy=None, trips_xy=None, weights=None, radius=None):
    """يبني المعايير حسب نوع المنشأة ويرجع (جدول مقيَّم، قائمة المعايير). weights يعدّل الأوزان الافتراضية."""
    cfg = PRESETS[kind]
    w = dict(cfg["weights"], **(weights or {}))
    xy = cand[["x", "y"]].to_numpy()
    r = radius or cfg["radius"]
    existing_xy = np.zeros((0, 2)) if existing_xy is None else np.asarray(existing_xy)
    crit = []
    if w.get("pop"):
        crit.append(Criterion("pop", pop_within(xy, pop, r), w["pop"], True, f"السكان ضمن {r} م"))
    if w.get("students"):
        crit.append(Criterion("students", pop_within(xy, pop, r, "students"), w["students"], True, f"الطلاب ضمن {r} م"))
    if w.get("low_income"):
        crit.append(Criterion("low_income", pop_within(xy, pop.assign(li=pop["pop"] * pop["low_income"]), r, "li"), w["low_income"], True, "سكان ذوو دخل محدود"))
    if w.get("poi") and poi is not None and len(poi):
        crit.append(Criterion("poi", poi_within(xy, poi, r), w["poi"], True, "نقاط الجذب الموزونة"))
    if w.get("gap"):
        crit.append(Criterion("gap", uncovered_pop(xy, pop, existing_xy, r), w["gap"], True, "سكان غير مخدومين"))
    if w.get("hub") and hubs_xy is not None and len(hubs_xy):
        crit.append(Criterion("hub", dist_to(xy, hubs_xy), w["hub"], False, "القرب من محور نقل"))
    if w.get("trips") and trips_xy is not None and len(trips_xy):
        tr = cKDTree(trips_xy)
        crit.append(Criterion("trips", np.array([len(l) for l in tr.query_ball_point(xy, r)], float), w["trips"], True, "كثافة الرحلات التاريخية"))
    if w.get("edge"):
        cx, cy = pop["x"].mean(), pop["y"].mean()
        crit.append(Criterion("edge", np.hypot(xy[:, 0] - cx, xy[:, 1] - cy), w["edge"], True, "البعد عن مركز المدينة"))
    return score(cand, crit), crit
