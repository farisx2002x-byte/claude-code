"""تخطيط مسارات الصباح لكل مدرسة بأسطول مختلط (OR-Tools).

كل طالب يركب من وقفة مركبته الموصى بها، والوقفة يخدمها مركبتها الموصى بها أو أي مركبة أصغر.
العقدة 0 = المدرسة، والخروج منها مجاني (مكان مبيت الباص غير معروف).
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

import config as C

BIG = 10 ** 7
PREFIX = {"large": "L", "medium": "M", "small": "S"}
FS = routing_enums_pb2.FirstSolutionStrategy


def cap_of(vk):
    return int(C.VEHICLES[vk]["seats"] * C.LOAD_FACTOR)


def allowed_types(cls):
    return C.VEH_ORDER[C.VEH_ORDER.index(cls):]


def arrival_seconds():
    h, m = C.SCHOOL_ARRIVAL.split(":")
    return int(h) * 3600 + int(m) * 60


def merge_stops(xy, cls, students):
    """يدمج الوقفات اللي بينها أقل من STOP_MERGE_M لنفس الفئة، ويقسم الوقفة الزايدة عن السعة.
    كل جزء ياخذ طلابه بس (بدون تكرار). يرجع قائمة وقفات: dict(x,y,cls,students[...])."""
    stops = []
    for c in C.VEH_ORDER:
        idx = np.where(cls == c)[0]
        if len(idx) == 0:
            continue
        pts = xy[idx]
        tree = cKDTree(pts)
        pairs = np.array(sorted(tree.query_pairs(C.STOP_MERGE_M)))
        n = len(pts)
        if len(pairs):
            g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
            lab = connected_components(g, directed=False)[1]
        else:
            lab = np.arange(n)
        capmax = max(cap_of(v) for v in allowed_types(c))
        for k in np.unique(lab):
            mem = idx[lab == k]
            ctr = xy[mem].mean(axis=0)
            order = mem[np.argsort(np.linalg.norm(xy[mem] - ctr, axis=1))]
            pos = xy[order[0]]
            for j in range(0, len(order), capmax):
                part = order[j:j + capmax]
                stops.append(dict(x=float(pos[0]), y=float(pos[1]), cls=c, students=[students[i] for i in part]))
    return stops


@dataclass
class Problem:
    school: str
    stops: list
    mats: dict = field(default_factory=dict)     # vk ← مصفوفة الأزمنة (ثواني) (n+1)×(n+1)
    nodes: dict = field(default_factory=dict)    # vk ← عقد الشبكة (0 = المدرسة)
    dropped: list = field(default_factory=list)  # طلاب بدون مسار (قبل الحل)


def prepare_school(school, sdf, net, school_xy):
    """يجهز الوقفات ومصفوفات الأزمنة لمدرسة. sdf فيه board_x/board_y وrec_vehicle ومعرّف الطالب في idx."""
    ok = ~sdf["board_x"].isna()
    dropped = list(sdf.loc[~ok, "idx"])
    sub = sdf[ok]
    cls = np.where(sub["rec_vehicle"].values == "pickup", "large", sub["rec_vehicle"].values)
    stops = merge_stops(sub[["board_x", "board_y"]].to_numpy(float), cls, list(sub["idx"]))
    P = Problem(school, stops, dropped=dropped)
    if not stops:
        return P
    sxy = np.array([[s["x"], s["y"]] for s in stops])
    keep = np.ones(len(stops), bool)
    nodes_by = {}
    for vk in C.VEH_ORDER:
        al = np.array([vk in allowed_types(s["cls"]) for s in stops])
        n_stop, d = net.snap(sxy, vk)
        n_sch, _ = net.snap([school_xy], vk)
        nodes_by[vk] = (al, n_stop, n_sch[0])
    for vk in C.VEH_ORDER:
        al, n_stop, n_sch = nodes_by[vk]
        if n_sch < 0:
            continue
        idx = np.where(al & (n_stop >= 0))[0]
        if len(idx) == 0:
            continue
        allnodes = np.concatenate([[n_sch], n_stop[idx]])
        m = net.matrix(vk, allnodes, allnodes)
        full = np.full((len(stops) + 1, len(stops) + 1), np.inf)
        ii = np.concatenate([[0], idx + 1])
        full[np.ix_(ii, ii)] = m
        P.mats[vk] = full
    # وقفة ما توصل المدرسة بأي مركبة مسموحة: تنحذف
    for i, s in enumerate(stops):
        can = any(vk in P.mats and np.isfinite(P.mats[vk][i + 1, 0]) for vk in allowed_types(s["cls"]))
        if not can:
            keep[i] = False
    if not keep.all():
        for i in np.where(~keep)[0]:
            P.dropped += stops[i]["students"]
        newidx = np.where(keep)[0]
        P.stops = [stops[i] for i in newidx]
        ii = np.concatenate([[0], newidx + 1])
        for vk in list(P.mats):
            P.mats[vk] = P.mats[vk][np.ix_(ii, ii)]
    return P


def _strategy(name):
    return getattr(FS, name)


def solve(P, max_ride_min=None, scale=1.0, seed_time=None):
    """يحل VRP لمدرسة. يرجع dict(routes=[...], dropped=[...], objective). كل مسار: vk, stops(order idx), cum times."""
    max_ride_min = max_ride_min or C.MAX_RIDE_MIN
    stops = P.stops
    n = len(stops)
    if n == 0:
        return dict(routes=[], dropped=list(P.dropped), objective=0)
    soft = int(max_ride_min * 60)
    hard = int(soft * C.HARD_RIDE_FACTOR)
    cnt = {c: sum(len(s["students"]) for s in stops if s["cls"] == c) for c in C.VEH_ORDER}
    caps = {v: cap_of(v) for v in C.VEH_ORDER}
    nveh = {
        "large": 2 * math.ceil(cnt["large"] / caps["large"]) + 2 if cnt["large"] else 0,
        "medium": (2 * math.ceil(cnt["medium"] / caps["medium"]) + math.ceil(cnt["large"] / caps["medium"]) + 2)
        if (cnt["medium"] or cnt["large"]) else 0,
        "small": (2 * math.ceil(cnt["small"] / caps["small"]) + 2) if cnt["small"] or cnt["medium"] or cnt["large"] else 0,
    }
    nveh = {v: (k if v in P.mats else 0) for v, k in nveh.items()}
    base_time = seed_time or min(max(C.VRP_TIME_MIN + 0.25 * n, C.VRP_TIME_MIN), C.VRP_TIME_MAX)
    per = max(1, int(round(base_time * scale / len(C.VRP_STRATEGIES))))
    best = None
    for strat in C.VRP_STRATEGIES:
        order = list(C.VEH_ORDER) if strat != "PATH_CHEAPEST_ARC" else list(reversed(C.VEH_ORDER))
        r = _solve_once(P, order, nveh, caps, soft, hard, strat, per)
        if r is not None and (best is None or r["objective"] < best["objective"]):
            best = r
    if best is None:
        return dict(routes=[], dropped=list(P.dropped) + [s for st in stops for s in st["students"]], objective=0)
    best["dropped"] = list(P.dropped) + best["dropped"]
    return best


def _solve_once(P, order, nveh, caps, soft, hard, strat, tlimit):
    stops = P.stops
    n = len(stops)
    vtype = [vk for vk in order for _ in range(nveh[vk])]
    nv = len(vtype)
    if nv == 0:
        return None
    manager = pywrapcp.RoutingIndexManager(n + 1, nv, 0)
    routing = pywrapcp.RoutingModel(manager)
    service = [0] + [C.STOP_SERVICE_S + C.STUDENT_SERVICE_S * len(s["students"]) for s in stops]
    cb = {}
    for vk in P.mats:
        M = P.mats[vk]
        T = np.where(np.isfinite(M), np.rint(M), BIG).astype(np.int64)
        T = T + np.array(service)[:, None]
        T[0, :] = np.where(np.isfinite(M[0, :]), 0, BIG)    # الخروج من المدرسة مجاني
        T[0, 0] = 0
        np.fill_diagonal(T, 0)
        cb[vk] = routing.RegisterTransitMatrix(T.tolist())
    dem = routing.RegisterUnaryTransitVector([0] + [len(s["students"]) for s in stops])
    routing.AddDimensionWithVehicleCapacity(dem, 0, [caps[v] for v in vtype], True, "cap")
    routing.AddDimensionWithVehicleTransits([cb[v] for v in vtype], 0, hard, True, "time")
    tdim = routing.GetDimensionOrDie("time")
    for k, vk in enumerate(vtype):
        routing.SetArcCostEvaluatorOfVehicle(cb[vk], k)
        routing.SetFixedCostOfVehicle(int(C.FIXED_COST * C.VEH_COST_FACTOR[vk]), k)
        tdim.SetCumulVarSoftUpperBound(routing.End(k), soft, C.LATE_PENALTY)
    for i, s in enumerate(stops, 1):
        idx = manager.NodeToIndex(i)
        ok_types = set(allowed_types(s["cls"]))
        bad = [k for k, vk in enumerate(vtype) if vk not in ok_types]
        if bad:
            routing.VehicleVar(idx).RemoveValues(bad)
        routing.AddDisjunction([idx], C.DROP_PENALTY)
    prm = pywrapcp.DefaultRoutingSearchParameters()
    prm.first_solution_strategy = _strategy(strat)
    prm.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    prm.time_limit.seconds = int(tlimit)
    sol = routing.SolveWithParameters(prm)
    if sol is None:
        return None
    routes, dropped = [], []
    seen = set()
    for k, vk in enumerate(vtype):
        idx = routing.Start(k)
        seq = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node:
                seq.append((node - 1, sol.Value(tdim.CumulVar(idx))))
            idx = sol.Value(routing.NextVar(idx))
        if seq:
            end = sol.Value(tdim.CumulVar(routing.End(k)))
            routes.append(dict(vk=vk, stops=[s for s, _ in seq], cum=[c for _, c in seq], end=end))
            seen |= {s for s, _ in seq}
    for i, s in enumerate(stops):
        if i not in seen:
            dropped += s["students"]
    return dict(routes=routes, dropped=dropped, objective=sol.ObjectiveValue())


def finalize(P, sol, net, school_xy, save_geometry=True):
    """يحول الحل لمسارات مرقمة بالوقفات وأوقات المرور (بالرجوع من وصول المدرسة) والشكل على الشبكة،
    ويرجع (routes_df, route_stops_df, student_assign_df, geoms)."""
    arr = arrival_seconds()
    counters = {v: 0 for v in C.VEH_ORDER}
    R, RS, SA, G = [], [], [], {}
    for r in sorted(sol["routes"], key=lambda r: (C.VEH_ORDER.index(r["vk"]), -len(r["stops"]))):
        counters[r["vk"]] += 1
        rid = f"{P.school}|{PREFIX[r['vk']]}{counters[r['vk']]:02d}"
        nodes_xy, length, load = [], 0.0, 0
        net_nodes = []
        mat = P.mats[r["vk"]]
        for o, (si, cum) in enumerate(zip(r["stops"], r["cum"]), 1):
            s = P.stops[si]
            ride = (r["end"] - cum)
            t_pass = arr - ride
            ns = len(s["students"])
            load += ns
            RS.append(dict(route=rid, school=P.school, order=o, x=s["x"], y=s["y"], students=ns,
                           time=_fmt(t_pass), ride_min=ride / 60.0, cls=s["cls"]))
            for sid in s["students"]:
                SA.append(dict(idx=sid, route=rid, board_time=_fmt(t_pass), ride_min=ride / 60.0))
        if save_geometry:
            pts = _route_geometry(net, r["vk"], [P.stops[i] for i in r["stops"]], school_xy)
            G[rid] = pts
            length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1))) if len(pts) > 1 else 0.0
        first_ride = (r["end"] - r["cum"][0]) / 60.0
        R.append(dict(route=rid, school=P.school, vk=r["vk"], stops=len(r["stops"]), students=load,
                      seats=C.VEHICLES[r["vk"]]["seats"], occupancy=load / C.VEHICLES[r["vk"]]["seats"],
                      duration_min=r["end"] / 60.0, longest_ride_min=first_ride, length_km=length / 1000.0,
                      start_time=_fmt(arr - (r["end"] - r["cum"][0]))))
    return pd.DataFrame(R), pd.DataFrame(RS), pd.DataFrame(SA), G


def _fmt(sec):
    sec = int(max(sec, 0))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}"


def _route_geometry(net, vk, stops, school_xy):
    """شكل المسار على الشبكة: من وقفة لوقفة ثم للمدرسة."""
    pts_xy = [np.array([s["x"], s["y"]]) for s in stops] + [np.array(school_xy)]
    nodes, _ = net.snap(np.array(pts_xy), vk)
    out = []
    for a, b in zip(nodes[:-1], nodes[1:]):
        if a < 0 or b < 0 or a == b:
            continue
        d, pred = net.shortest(vk, int(a), "time")
        if not np.isfinite(d[b]):
            continue
        path = [int(b)]
        while path[-1] != a and pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        path = path[::-1]
        out.append(net.path_geometry(path))
    return np.vstack(out) if out else np.array([pts_xy[0], pts_xy[-1]])


def plan_all(df, net, schools_xy, max_ride_min=None, scale=1.0, save=True, only=None, log=print, cache=None):
    """يخطط كل المدارس. يرجع (routes, route_stops, assign, geoms, no_route_idx, problems)."""
    Rs, RSs, SAs, Gs, nores = [], [], [], {}, []
    probs = {}
    names = [s for s in df["school_official"].unique() if s in schools_xy and (only is None or s in only)]
    for k, sname in enumerate(names, 1):
        sdf = df[df["school_official"] == sname]
        if cache is not None and sname in cache:
            P = cache[sname]          # مصفوفات الأزمنة محفوظة بين تشغيلات السيناريوهات
        else:
            P = prepare_school(sname, sdf, net, schools_xy[sname])
            if cache is not None:
                cache[sname] = P
        probs[sname] = P
        sol = solve(P, max_ride_min, scale)
        R, RS, SA, G = finalize(P, sol, net, schools_xy[sname], save_geometry=save)
        Rs.append(R); RSs.append(RS); SAs.append(SA); Gs.update(G)
        nores += sol["dropped"]
        log(f"[{k}/{len(names)}] {sname}: {len(R)} مسار، بدون مسار {len(sol['dropped'])}")
    cat = lambda L: pd.concat([x for x in L if len(x)], ignore_index=True) if any(len(x) for x in L) else pd.DataFrame()
    return cat(Rs), cat(RSs), cat(SAs), Gs, nores, probs
