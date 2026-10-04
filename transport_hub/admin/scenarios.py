"""سجل السيناريوهات: حفظ نتائج كل سيناريو ومقارنتها مع خط الأساس."""
import pandas as pd


class ScenarioBook:
    KEY = "scenarios"

    def __init__(self, ws):
        self.ws = ws
        self.data = ws.obj(self.KEY) or {}

    def save(self, name, params, kpis):
        self.data[name] = dict(params=params, kpis={k: float(v) for k, v in kpis.items()})
        self.ws.save_obj(self.KEY, self.data)
        self.ws.log("scenario_saved", name=name)

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
