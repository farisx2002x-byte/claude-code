"""العدالة المكانية: توزيع الخدمة على الأحياء والفئات الأقل دخلاً، ومؤشر Gini، وترتيب الأولويات."""
import numpy as np
import pandas as pd


def gini(values, weights):
    """Gini موزون بالسكان لتوزيع مؤشر الخدمة (0 = تساوٍ تام)."""
    v, w = np.asarray(values, float), np.asarray(weights, float)
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.cumsum(w) / w.sum()
    cv = np.cumsum(v * w) / (v * w).sum() if (v * w).sum() > 0 else cw
    cw0, cv0 = np.concatenate([[0], cw]), np.concatenate([[0], cv])
    return float(1 - np.sum((cw0[1:] - cw0[:-1]) * (cv0[1:] + cv0[:-1])))


def lorenz(values, weights, n=50):
    v, w = np.asarray(values, float), np.asarray(weights, float)
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.concatenate([[0], np.cumsum(w) / w.sum()])
    cv = np.concatenate([[0], np.cumsum(v * w) / max((v * w).sum(), 1e-12)])
    xs = np.linspace(0, 1, n)
    return pd.DataFrame({"share_pop": xs, "share_service": np.interp(xs, cw, cv)})


def by_district(cov):
    """cov: ناتج coverage+accessibility (فيه district, pop, access_index, covered_400, low_income)."""
    rows = []
    for d, g in cov.groupby("district"):
        p = g["pop"].sum()
        li = (g["pop"] * g["low_income"]).sum() / p if p else 0
        rows.append(dict(الحي=d, السكان=int(p), تغطية_400=round(100 * g.loc[g["covered_400"], "pop"].sum() / p, 1) if p else 0,
                         مؤشر_الخدمة=round(float(np.average(g["access_index"], weights=g["pop"])) if p else 0, 2),
                         نسبة_محدودي_الدخل=round(li, 2), بلا_خدمة=int(g.loc[g["access_index"] == 0, "pop"].sum())))
    return pd.DataFrame(rows).sort_values("مؤشر_الخدمة").reset_index(drop=True)


def priority_zones(cov, top=15):
    """أولوية التدخل = السكان × (1 − الخدمة المطبّعة) × (1 + نسبة محدودي الدخل). الأعلى = الأحوج."""
    c = cov.copy()
    norm = np.clip(c["access_index"] / max(c["access_index"].quantile(0.9), 1e-9), 0, 1)
    c["priority"] = c["pop"] * (1 - norm) * (1 + c["low_income"])
    cols = [x for x in ("zone_id", "name", "district", "pop", "access_index", "walk_to_stop_m", "low_income", "priority") if x in c]
    return c.sort_values("priority", ascending=False).head(top)[cols].reset_index(drop=True)
