"""سجل السيناريوهات: حفظ نتائج كل سيناريو ومقارنتها مع خط الأساس، وترتيبها وحساب فعالية التكلفة."""

import numpy as np
import pandas as pd

# اتجاه التحسّن لكل مؤشر: +1 الأعلى أفضل، -1 الأقل أفضل
DIRECTION = {
    "covered_400_pct": 1,
    "covered_800_pct": 1,
    "avg_access_index": 1,
    "pop_no_service": -1,
}
DEFAULT_WEIGHTS = {"covered_400_pct": 0.35, "covered_800_pct": 0.15, "avg_access_index": 0.30, "pop_no_service": 0.20}
EPS = 1e-9


def direction_of(kpi):
    return DIRECTION.get(kpi, 1)


class ScenarioBook:
    KEY = "scenarios"

    def __init__(self, ws):
        self.ws = ws
        self.data = ws.obj(self.KEY) or {}

    def save(self, name, params, kpis, cost=None):
        self.data[name] = dict(params=params, kpis={k: float(v) for k, v in kpis.items()}, cost=None if cost is None else float(cost))
        self.ws.save_obj(self.KEY, self.data)
        self.ws.log("scenario_saved", name=name)

    def set_cost(self, name, cost):
        """تكلفة السيناريو (ريال) لحساب فعالية التكلفة."""
        if name in self.data:
            self.data[name]["cost"] = None if cost is None else float(cost)
            self.ws.save_obj(self.KEY, self.data)

    def delete(self, name):
        self.data.pop(name, None)
        self.ws.save_obj(self.KEY, self.data)

    def compare(self, baseline=None):
        """جدول مؤشرات كل سيناريو، مع الفرق عن الأساس (أول سيناريو أو المحدد)."""
        if not self.data:
            return pd.DataFrame()
        df = pd.DataFrame({n: s["kpis"] for n, s in self.data.items()}).T
        base = baseline or df.index[0]
        for c in list(df.columns):
            df[f"Δ {c}"] = df[c] - df.loc[base, c]
        return df

    def kpi_frame(self):
        return pd.DataFrame({n: s["kpis"] for n, s in self.data.items()}).T

    def costs(self):
        return pd.Series({n: s.get("cost") for n, s in self.data.items()}, dtype=float)

    def detailed(self, baseline=None):
        """جدول طويل: سيناريو × مؤشر مع القيمة والفرق والنسبة والحكم (أفضل / أسوأ / ثابت) حسب اتجاه المؤشر."""
        df = self.kpi_frame()
        if df.empty:
            return pd.DataFrame()
        base = baseline or df.index[0]
        rows = []
        for sc in df.index:
            for k in df.columns:
                v, b = df.loc[sc, k], df.loc[base, k]
                d = v - b
                good = d * direction_of(k)
                rows.append(
                    dict(
                        scenario=sc,
                        kpi=k,
                        value=v,
                        base=b,
                        delta=d,
                        delta_pct=(100 * d / b) if abs(b) > EPS else np.nan,
                        verdict="ثابت" if abs(d) < 1e-6 else ("أفضل" if good > 0 else "أسوأ"),
                    )
                )
        return pd.DataFrame(rows)

    def rank(self, weights=None, baseline=None):
        """درجة 0–100 لكل سيناريو: تطبيع كل مؤشر بين أسوأ وأفضل قيمة (حسب الاتجاه) ثم وزن مرجّح."""
        df = self.kpi_frame()
        if df.empty:
            return pd.DataFrame()
        w = {k: v for k, v in (weights or DEFAULT_WEIGHTS).items() if k in df.columns and v > 0}
        if not w:
            return pd.DataFrame()
        tot = sum(w.values())
        score = pd.Series(0.0, index=df.index)
        for k, wt in w.items():
            col = df[k] * direction_of(k)
            rng = col.max() - col.min()
            norm = (col - col.min()) / rng if rng > EPS else pd.Series(0.5, index=df.index)
            score += norm * wt / tot
        out = pd.DataFrame({"score": (100 * score).round(1)})
        base = baseline or df.index[0]
        out["score_vs_base"] = (out["score"] - out.loc[base, "score"]).round(1)
        costs = self.costs()
        out["cost"] = costs
        out["rank"] = out["score"].rank(ascending=False, method="min").astype(int)
        return out.sort_values("rank")

    def cost_effectiveness(self, kpi="covered_400_pct", baseline=None):
        """تكلفة كل نقطة مئوية تحسّن في المؤشر الرئيسي (ريال). يُهمل السيناريو بلا تكلفة أو بلا تحسّن."""
        df = self.kpi_frame()
        if df.empty or kpi not in df.columns:
            return pd.DataFrame()
        base = baseline or df.index[0]
        costs = self.costs()
        rows = []
        for sc in df.index:
            if sc == base:
                continue
            gain = (df.loc[sc, kpi] - df.loc[base, kpi]) * direction_of(kpi)
            c = costs.get(sc, np.nan)
            ok = pd.notna(c) and gain > EPS
            rows.append(dict(scenario=sc, gain=round(gain, 3), cost=c, cost_per_point=round(c / gain) if ok else np.nan))
        return pd.DataFrame(rows).sort_values("cost_per_point", na_position="last").reset_index(drop=True)

    def best(self, weights=None):
        r = self.rank(weights)
        return None if r.empty else r.index[0]
