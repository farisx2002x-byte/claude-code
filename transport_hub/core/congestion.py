"""الازدحام وأزمنة القيادة: عوامل ازدحام لكل فترة من اليوم (عامة ولكل ضلع في الشبكة)، تُتعلَّم من بيانات تتبع الحافلات (AVL)
أو تُدخل يدوياً كمنحنى ساعات. زمن القيادة = زمن السير الحر × عامل الازدحام."""

import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

PERIODS = {"ليل": (0, 6), "ذروة صباحية": (6, 9), "منتصف النهار": (9, 15), "ذروة مسائية": (15, 19), "مساء": (19, 24)}
PERIOD_KEYS = list(PERIODS)
FACTOR_MIN, FACTOR_MAX = 0.7, 8.0


def period_of_hour(h):
    h = int(h) % 24
    for k, (a, b) in PERIODS.items():
        if a <= h < b:
            return k
    return PERIOD_KEYS[-1]


def period_of_seconds(s):
    return period_of_hour((s % 86400) // 3600)


@dataclass
class Profile:
    """عوامل الازدحام: period_factor (عام لكل فترة)، وedge_factor اختياري (مصفوفة بحجم أضلاع الشبكة لكل فترة)."""

    period_factor: dict
    edge_factor: dict | None = None
    edge_obs: np.ndarray | None = None  # وزن الملاحظات لكل ضلع (م × عدد المشاهدات): >0 = ضلع مرصود فعلاً
    net_fp: str | None = None
    source: str = "يدوي"
    diagnostics: pd.DataFrame | None = None
    key: str = field(default_factory=lambda: uuid.uuid4().hex)

    def factor(self, period):
        return float(self.period_factor.get(period, np.mean(list(self.period_factor.values()))))

    def edge_factors(self, period, net):
        arr = (self.edge_factor or {}).get(period)
        return arr if arr is not None else np.full(net.n_edges, self.factor(period))

    def compatible(self, net):
        return self.edge_factor is None or self.net_fp == net.fingerprint

    def table(self):
        return pd.DataFrame(
            {"period": PERIOD_KEYS, "factor": [self.factor(p) for p in PERIOD_KEYS], "speed_index": [1 / self.factor(p) for p in PERIOD_KEYS]}
        )


def default_profile(factor=1.25):
    return Profile({p: factor for p in PERIOD_KEYS}, source="افتراضي")


def from_hourly(df, hour="hour", factor="factor"):
    """منحنى ساعات يدوي: عمود ساعة (0–23) وعامل ازدحام (زمن الرحلة ÷ زمن السير الحر، ≥ 0.7). أو عمود speed_ratio (السرعة ÷ السير الحر)."""
    d = df.copy()
    if factor not in d and "speed_ratio" in d:
        d[factor] = 1 / pd.to_numeric(d["speed_ratio"], errors="coerce")
    if hour not in d or factor not in d:
        raise ValueError("منحنى الازدحام: المطلوب عمودا hour وfactor (أو speed_ratio)")
    d[hour] = pd.to_numeric(d[hour], errors="coerce")
    d[factor] = pd.to_numeric(d[factor], errors="coerce")
    d = d.dropna(subset=[hour, factor])
    d = d[(d[hour] >= 0) & (d[hour] < 24)]
    if d.empty:
        raise ValueError("منحنى الازدحام: لا صفوف صالحة")
    d["p"] = d[hour].map(period_of_hour)
    pf = d.groupby("p")[factor].mean().clip(FACTOR_MIN, FACTOR_MAX).to_dict()
    fill = float(np.mean(list(pf.values())))
    return Profile({p: float(pf.get(p, fill)) for p in PERIOD_KEYS}, source="منحنى ساعات مرفوع")


def learn_from_avl(net, feed, avl, proj, prior_m=400.0, min_obs=3):
    """يتعلم الازدحام من AVL على الشبكة. لكل زوج محطتين متتاليتين نقارن زمن القيادة الفعلي (فرق الأزمنة − التوقف المجدول)
    بزمن السير الحر على أقصر مسار في الشبكة، فنحصل عامل ازدحام لكل (زوج، فترة). العامل العام للفترة = وسيط موزون،
    وعامل كل ضلع = متوسط موزون بالطول مع انكماش نحو العام (prior_m متراً مكافئاً) فلا تُبالغ الأضلاع قليلة المشاهدات.
    يرجع Profile (فيه diagnostics: ملاحظات وعوامل لكل فترة)."""
    st = feed.stop_times[["trip_id", "stop_id", "stop_sequence", "arr", "dep"]].merge(feed.stops[["stop_id", "stop_lat", "stop_lon"]], on="stop_id")
    st["x"], st["y"] = proj.xy(st["stop_lon"], st["stop_lat"])
    a = avl[["date", "trip_id", "stop_id", "act", "sched"]].merge(st, on=["trip_id", "stop_id"]).sort_values(["date", "trip_id", "stop_sequence"])
    g = a.groupby(["date", "trip_id"])
    for c in ("act", "x", "y", "stop_id", "dep", "arr", "stop_sequence"):
        a[c + "_p"] = g[c].shift()
    a = a.dropna(subset=["act_p"])
    a = a[a["stop_sequence"] == a["stop_sequence_p"] + 1]
    a["dwell_p"] = a["dep_p"] - a["arr_p"]  # التوقف المجدول في المحطة السابقة
    a["drive"] = a["act"] - a["act_p"] - a["dwell_p"].fillna(0).clip(lower=0)
    a = a[(a["drive"] >= 5) & (a["drive"] <= 3600)]
    a["period"] = (a["sched"] // 3600).map(period_of_hour)
    pairs = (
        a.groupby(["stop_id_p", "stop_id", "period"])
        .agg(n=("drive", "size"), med=("drive", "median"), xa=("x_p", "first"), ya=("y_p", "first"), xb=("x", "first"), yb=("y", "first"))
        .reset_index()
    )
    pairs = pairs[pairs["n"] >= min_obs]
    n_edges = net.n_edges
    num = {p: np.zeros(n_edges) for p in PERIOD_KEYS}
    den = {p: np.zeros(n_edges) for p in PERIOD_KEYS}
    rows = []
    cache = {}
    for r in pairs.itertuples():
        key = (r.stop_id_p, r.stop_id)
        if key not in cache:
            edges, _ = net.path_edges([r.xa, r.ya], [r.xb, r.yb])
            cache[key] = None if edges is None or len(edges) == 0 else (edges, float(net._dt[edges].sum()))
        if cache[key] is None:
            continue
        edges, t_free = cache[key]
        ratio = float(np.clip(r.med / max(t_free, 1.0), FACTOR_MIN, FACTOR_MAX))
        rows.append((r.period, ratio, r.n, t_free))
        w = r.n * net._dl[edges]
        np.add.at(num[r.period], edges, w * ratio)
        np.add.at(den[r.period], edges, w)
    if not rows:
        raise ValueError("لا ملاحظات كافية: تأكد أن AVL يغطي رحلات الجدول (نفس trip_id وstop_id) وأن الشبكة تغطي المحطات")
    obs = pd.DataFrame(rows, columns=["period", "ratio", "n", "t_free"])
    gfac, diag = {}, []
    for p in PERIOD_KEYS:
        o = obs[obs["period"] == p]
        if len(o):
            order = np.argsort(o["ratio"].to_numpy())
            w = (o["n"] * o["t_free"]).to_numpy()[order]
            gfac[p] = float(o["ratio"].to_numpy()[order][np.searchsorted(np.cumsum(w), w.sum() / 2)])
        diag.append(dict(period=p, pairs=int(len(o)), obs=int(o["n"].sum()) if len(o) else 0))
    fallback = float(np.average(obs["ratio"], weights=obs["n"] * obs["t_free"]))
    for p in PERIOD_KEYS:
        gfac.setdefault(p, fallback)
    edge_factor = {p: np.where(den[p] > 0, (num[p] + prior_m * gfac[p]) / (den[p] + prior_m), gfac[p]) for p in PERIOD_KEYS}
    d = pd.DataFrame(diag)
    d["factor"] = [gfac[p] for p in PERIOD_KEYS]
    d["speed_index"] = 1 / d["factor"]
    d["observed_links"] = [int((den[p] > 0).sum()) for p in PERIOD_KEYS]
    return Profile(gfac, edge_factor, sum(den.values()), net.fingerprint, "تعلّم من AVL", d)


def worst_links(profile, net, period, top=25, min_obs=1.0):
    """أكثر الأضلاع ازدحاماً في الفترة (المرصودة فعلاً): مع إحداثيات طرفيها (مسقطة) لرسمها."""
    if profile.edge_factor is None or profile.edge_obs is None:
        return pd.DataFrame()
    f = profile.edge_factor[period]
    idx = np.where(profile.edge_obs >= min_obs)[0]
    idx = idx[np.argsort(-f[idx])][:top]
    xy = net.node_xy
    return pd.DataFrame(
        {
            "factor": f[idx],
            "length_m": net._dl[idx],
            "xa": xy[net._du[idx], 0],
            "ya": xy[net._du[idx], 1],
            "xb": xy[net._dv[idx], 0],
            "yb": xy[net._dv[idx], 1],
        }
    )
