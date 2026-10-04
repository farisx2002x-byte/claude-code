"""اختيار المواقع: أقصى تغطية (Maximal Covering) وp-median للمستودعات والمراكز."""
import heapq

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


def _cover_lists(demand_xy, cand_xy, radius):
    tree = cKDTree(demand_xy)
    return tree.query_ball_point(cand_xy, radius)


def max_coverage(demand_xy, weights, cand_xy, radius, p, existing_xy=None, bonus=None, min_gain=1e-9):
    """يختار حتى p موقعاً من المرشحين لتعظيم الطلب المغطى ضمن radius (متر مستقيم) غير المغطى بالمواقع الحالية.
    bonus: مكافأة لكل مرشح (مثل قرب نقاط الجذب) تُضاف للمكسب. الخوارزمية جشعة مع تقييم كسول (ضمان 63%).
    يرجع (جدول الاختيار، نسبة التغطية قبل/بعد)."""
    w = np.asarray(weights, float)
    dxy = np.asarray(demand_xy, float)
    covered = np.zeros(len(w), bool)
    if existing_xy is not None and len(existing_xy):
        for lst in cKDTree(dxy).query_ball_point(np.asarray(existing_xy, float), radius):
            covered[lst] = True
    before = w[covered].sum() / max(w.sum(), 1e-9)
    lists = [np.asarray(l, int) for l in _cover_lists(dxy, np.asarray(cand_xy, float), radius)]
    bonus = np.zeros(len(lists)) if bonus is None else np.asarray(bonus, float)
    heap = [(-(w[l][~covered[l]].sum() + bonus[i]), i) for i, l in enumerate(lists)]
    heapq.heapify(heap)
    rows, cum = [], w[covered].sum()
    total = max(w.sum(), 1e-9)
    while heap and len(rows) < p:
        neg, i = heapq.heappop(heap)
        gain = w[lists[i]][~covered[lists[i]]].sum() + bonus[i]       # إعادة التقييم (كسول)
        if heap and gain < -heap[0][0] - 1e-12:
            heapq.heappush(heap, (-gain, i))
            continue
        if gain <= min_gain:
            break
        newly = w[lists[i]][~covered[lists[i]]].sum()
        covered[lists[i]] = True
        cum += newly
        rows.append(dict(rank=len(rows) + 1, cand=i, x=cand_xy[i][0], y=cand_xy[i][1], gain=newly, bonus=bonus[i],
                         cum_covered_pct=100 * cum / total))
    return pd.DataFrame(rows), (100 * before, 100 * cum / total)


def max_coverage_exact(demand_xy, weights, cand_xy, radius, p, existing_xy=None, time_s=20):
    """حل دقيق بـ CP-SAT للأحجام الصغيرة (للمقارنة مع الجشع). يرجع فهارس المرشحين المختارين."""
    from ortools.sat.python import cp_model
    w = np.rint(np.asarray(weights, float)).astype(int)
    dxy = np.asarray(demand_xy, float)
    pre = np.zeros(len(w), bool)
    if existing_xy is not None and len(existing_xy):
        for lst in cKDTree(dxy).query_ball_point(np.asarray(existing_xy, float), radius):
            pre[lst] = True
    lists = _cover_lists(dxy, np.asarray(cand_xy, float), radius)
    cover_by = [[] for _ in range(len(w))]
    for c, l in enumerate(lists):
        for d in l:
            cover_by[d].append(c)
    m = cp_model.CpModel()
    y = [m.NewBoolVar(f"y{c}") for c in range(len(lists))]
    z = {}
    for d in range(len(w)):
        if pre[d] or not cover_by[d]:
            continue
        z[d] = m.NewBoolVar(f"z{d}")
        m.Add(z[d] <= sum(y[c] for c in cover_by[d]))
    m.Add(sum(y) <= p)
    m.Maximize(sum(int(w[d]) * z[d] for d in z))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_s
    s.parameters.num_workers = 4
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    return [c for c in range(len(lists)) if s.Value(y[c])]


def p_median(demand_xy, weights, cand_xy, p, max_iter=20):
    """p-median (مستودعات/مراكز): يقلل مجموع المسافات الموزونة. بداية جشعة ثم تبديل Teitz–Bart."""
    from scipy.spatial.distance import cdist
    w = np.asarray(weights, float)
    D = cdist(np.asarray(demand_xy, float), np.asarray(cand_xy, float))
    n_c = D.shape[1]
    chosen = []
    cur = np.full(len(w), np.inf)
    for _ in range(min(p, n_c)):
        costs = [(w * np.minimum(cur, D[:, c])).sum() if c not in chosen else np.inf for c in range(n_c)]
        c = int(np.argmin(costs))
        chosen.append(c)
        cur = np.minimum(cur, D[:, c])
    for _ in range(max_iter):
        improved = False
        base = (w * D[:, chosen].min(axis=1)).sum()
        for k in range(len(chosen)):
            rest = [c for j, c in enumerate(chosen) if j != k]
            rest_min = D[:, rest].min(axis=1) if rest else np.full(len(w), np.inf)
            costs = (w[:, None] * np.minimum(rest_min[:, None], D)).sum(axis=0)
            costs[rest] = np.inf
            c = int(np.argmin(costs))
            if costs[c] < base - 1e-9:
                chosen[k] = c
                base = costs[c]
                improved = True
        if not improved:
            break
    assign = D[:, chosen].argmin(axis=1)
    cost = float((w * D[np.arange(len(w)), np.array(chosen)[assign]]).sum())
    sites = pd.DataFrame({"cand": chosen, "x": np.asarray(cand_xy)[chosen, 0], "y": np.asarray(cand_xy)[chosen, 1],
                          "load": [float(w[assign == k].sum()) for k in range(len(chosen))]})
    return sites, assign, cost
