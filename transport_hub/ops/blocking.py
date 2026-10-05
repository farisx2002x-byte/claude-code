"""جدولة المركبات (Vehicle Blocking): أقل عدد مركبات يغطي كل رحلات الجدول، مع التوصيلات الفارغة والاستراحات،
ثم قطع العمل للسائقين (Duties) وفق حدود القيادة المتواصلة."""

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_bipartite_matching

from transport_hub.core.access import Access
from transport_hub.core.congestion import period_of_seconds

DEADHEAD_KMH = 30.0
BIG = 1e9


def trip_endpoints(feed, proj, weekday=None, access=None):
    """جدول الرحلات مع أول/آخر محطة وإحداثياتها: trip_id, route_id, start, end, from_x/y, to_x/y, km."""
    from transport_hub.transit.service import trip_table

    t = trip_table(feed, weekday)[["trip_id", "route_id", "direction_id", "start", "end"]]
    st = feed.stop_times.merge(feed.stops[["stop_id", "stop_lat", "stop_lon"]], on="stop_id")
    st["x"], st["y"] = proj.xy(st["stop_lon"], st["stop_lat"])
    g = st.sort_values(["trip_id", "stop_sequence"]).groupby("trip_id")
    first = g.first()[["x", "y"]].rename(columns={"x": "from_x", "y": "from_y"})
    last = g.last()[["x", "y"]].rename(columns={"x": "to_x", "y": "to_y"})
    seg = st.sort_values(["trip_id", "stop_sequence"]).copy()
    seg["dx"] = seg.groupby("trip_id")["x"].diff()
    seg["dy"] = seg.groupby("trip_id")["y"].diff()
    access = access or Access()
    seg["px"] = seg.groupby("trip_id")["x"].shift()
    seg["py"] = seg.groupby("trip_id")["y"].shift()
    legs = seg.dropna(subset=["px"])[["trip_id", "px", "py", "x", "y"]].copy()
    uniq = legs[["px", "py", "x", "y"]].round(1).drop_duplicates().reset_index(drop=True)
    uniq["d"] = access.drive_pairs(uniq[["px", "py"]].to_numpy(), uniq[["x", "y"]].to_numpy(), "length")  # الحافلة تتبع الشوارع واتجاهها الواحد
    legs = legs.assign(px=legs["px"].round(1), py=legs["py"].round(1), x=legs["x"].round(1), y=legs["y"].round(1)).merge(
        uniq, on=["px", "py", "x", "y"], how="left"
    )
    km = legs.groupby("trip_id")["d"].sum() / 1000
    out = t.merge(first, left_on="trip_id", right_index=True).merge(last, left_on="trip_id", right_index=True)
    out["km"] = out["trip_id"].map(km)
    return out.sort_values("start").reset_index(drop=True)


def _deadhead(trips, access):
    """مصفوفة التوصيل الفارغ من نهاية كل رحلة لبداية كل رحلة: مسافة (م) وزمن (ث). الزمن يتبع ازدحام فترة اليوم التي تنتهي فيها الرحلة
    (ملف الازدحام إن وُجد)، على الشوارع باتجاهها أو بالتقدير. تُحسب على النقاط الفريدة فقط."""
    ends = trips[["to_x", "to_y"]].round(1).to_numpy()
    starts = trips[["from_x", "from_y"]].round(1).to_numpy()
    ue, ie = np.unique(ends, axis=0, return_inverse=True)
    us, is_ = np.unique(starts, axis=0, return_inverse=True)
    ie, is_ = ie.ravel(), is_.ravel()
    dm = access.drive_matrix(ue, us, "length")[np.ix_(ie, is_)]
    periods = trips["end"].map(period_of_seconds).to_numpy()
    ds = np.empty_like(dm)
    for p in np.unique(periods):
        rows = np.where(periods == p)[0]
        tm = access.with_period(p).drive_matrix(ue, us, "time")
        ds[rows] = tm[np.ix_(ie[rows], is_)]
    return dm, ds


def _compat(trips, layover_s, max_gap_s, max_deadhead_km, access=None):
    """مصفوفة التوافق: الرحلة j تلي i لو وصلنا النهاية + استراحة + وقت التوصيل الفارغ قبل بدء j، وبدون انتظار أطول من max_gap."""
    end, start = trips["end"].to_numpy(), trips["start"].to_numpy()
    dh_m, dh_s = _deadhead(trips, access or Access())
    ready = end[:, None] + layover_s + dh_s
    ok = (ready <= start[None, :]) & (start[None, :] - ready <= max_gap_s) & (dh_m <= max_deadhead_km * 1000)
    np.fill_diagonal(ok, False)
    wait = start[None, :] - end[:, None] - dh_s
    return ok, wait, dh_m


def build_blocks(trips, layover_min=5, max_gap_min=90, minimize_cost=True, depot_xy=None, max_deadhead_km=3.0, access=None):
    """يرجع (blocks: جدول رحلة→مركبة، summary). عدد المركبات = n − حجم المطابقة العظمى (مسار أدنى في مخطط الاتجاه الأحادي).
    minimize_cost: بين الحلول بنفس عدد المركبات يختار أقل انتظار وتوصيل فارغ (n ≤ 2500)."""
    trips = trips.reset_index(drop=True)
    n = len(trips)
    access = access or Access()
    ok, wait, dh_m = _compat(trips, layover_min * 60, max_gap_min * 60, max_deadhead_km, access)
    if n <= 2500 and minimize_cost:
        cost = np.where(ok, wait / 60 + dh_m / 1000 * 6, BIG)
        r, c = linear_sum_assignment(cost)
        nxt = np.full(n, -1)
        for i, j in zip(r, c):
            if ok[i, j]:
                nxt[i] = j
    else:
        m = maximum_bipartite_matching(csr_matrix(ok.astype(np.int8)), perm_type="column")
        nxt = np.where(m >= 0, m, -1)  # m[i] = العمود المقابل للصف i
    has_prev = np.zeros(n, bool)
    has_prev[nxt[nxt >= 0]] = True
    veh = np.full(n, -1)
    seq = np.zeros(n, int)
    v = 0
    for s in np.where(~has_prev)[0]:
        k, i = 0, s
        while i >= 0:
            veh[i], seq[i] = v, k
            k += 1
            i = nxt[i]
        v += 1
    blocks = trips.assign(vehicle=veh, seq=seq).sort_values(["vehicle", "seq"]).reset_index(drop=True)
    summary = block_stats(blocks, trips, depot_xy, access)
    return blocks, summary


def block_stats(blocks, trips, depot_xy=None, access=None):
    """إحصاءات: المركبات، ساعات الخدمة والاستراحة، التوصيل الفارغ، الإشغال، والحد الأدنى النظري (أقصى تزامن للرحلات)."""
    access = access or Access()
    ev = np.concatenate([np.ones(len(trips)), -np.ones(len(trips))])
    t = np.concatenate([trips["start"].to_numpy(), trips["end"].to_numpy()])
    peak = int(np.max(np.cumsum(ev[np.lexsort((ev, t))])))  # النهايات قبل البدايات عند التساوي
    service_h = float((blocks["end"] - blocks["start"]).sum() / 3600)
    dead_km, idle_h = 0.0, 0.0
    pull_km = 0.0
    for _, g in blocks.groupby("vehicle"):
        a, b = g.iloc[:-1], g.iloc[1:]
        if len(a):
            ends, starts = a[["to_x", "to_y"]].to_numpy(), b[["from_x", "from_y"]].to_numpy()
            d = access.drive_pairs(ends, starts, "length")
            tsec = np.array(
                [
                    access.with_period(period_of_seconds(e)).drive_pairs(ends[i : i + 1], starts[i : i + 1], "time")[0]
                    for i, e in enumerate(a["end"].to_numpy())
                ]
            )
            dead_km += d.sum() / 1000
            idle_h += float((b["start"].to_numpy() - a["end"].to_numpy() - tsec).sum() / 3600)
        if depot_xy is not None:
            first, last = g.iloc[0], g.iloc[-1]
            dep = np.array([depot_xy], float)
            pull_km += float(
                (
                    access.drive_pairs(dep, np.array([[first["from_x"], first["from_y"]]]), "length")[0]
                    + access.drive_pairs(np.array([[last["to_x"], last["to_y"]]]), dep, "length")[0]
                )
                / 1000
            )
    veh = blocks["vehicle"].nunique()
    span_h = float(sum((g["end"].max() - g["start"].min()) for _, g in blocks.groupby("vehicle")) / 3600)
    return dict(
        trips=len(trips),
        vehicles=int(veh),
        theoretical_min=peak,
        in_service_h=round(service_h, 1),
        idle_h=round(idle_h, 1),
        deadhead_km=round(dead_km, 1),
        pull_in_out_km=round(pull_km, 1),
        service_km=round(float(trips["km"].sum()), 1),
        utilization=round(service_h / span_h, 3) if span_h else 0.0,
    )


def vehicle_table(blocks):
    g = blocks.groupby("vehicle")
    out = g.agg(
        trips=("trip_id", "size"),
        first_start=("start", "min"),
        last_end=("end", "max"),
        km=("km", "sum"),
        routes=("route_id", lambda s: "، ".join(sorted(set(s)))),
    )
    out["span_h"] = (out["last_end"] - out["first_start"]) / 3600
    out["in_service_h"] = g.apply(lambda d: (d["end"] - d["start"]).sum() / 3600, include_groups=False)
    for c in ("first_start", "last_end"):
        out[c] = out[c].map(lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}")
    return out.reset_index()


def duties(blocks, max_drive_h=4.5, min_break_min=15, max_duty_h=9.0, signon_min=15):
    """قطع عمل السائقين: نمد القطعة لأبعد ما تسمح به حدود القيادة المتواصلة وطول الوردية، ونقطع عند آخر فرصة تبديل
    (فجوة ≥ min_break). لو ما فيه فرصة قبل الحد تُعلَّم القطعة مخالفة. يرجع (جدول القطع، ملخص)."""
    rows = []
    for v, g in blocks.groupby("vehicle"):
        t = g.sort_values("start")[["trip_id", "start", "end"]].to_numpy()
        n = len(t)
        i = 0
        while i < n:
            j, drive, last_relief = i, 0.0, None
            while j < n:
                d_j = (t[j][2] - t[j][1]) / 3600
                dur = (t[j][2] - t[i][1]) / 3600
                if j > i and (drive + d_j > max_drive_h or dur > max_duty_h):
                    break
                drive += d_j
                if j + 1 < n and (t[j + 1][1] - t[j][2]) / 60 >= min_break_min:
                    last_relief = (j, drive)
                j += 1
            if j >= n:
                end_j, drv = n - 1, drive
            elif last_relief is not None:
                end_j, drv = last_relief
            else:
                end_j, drv = j - 1, drive  # لا فرصة تبديل ضمن الحدود: نقطع قسراً ونعلّم المخالفة
            dur = (t[end_j][2] - t[i][1]) / 3600
            no_relief = end_j + 1 < n and (t[end_j + 1][1] - t[end_j][2]) / 60 < min_break_min  # تسليم بدون فجوة كافية
            rows.append(
                dict(
                    vehicle=v,
                    start=t[i][1],
                    end=t[end_j][2],
                    drive_h=drv,
                    trips=end_j - i + 1,
                    violation=bool(drv > max_drive_h + 1e-9 or dur > max_duty_h + 1e-9 or no_relief),
                )
            )
            i = end_j + 1
    d = pd.DataFrame(rows)
    if d.empty:
        return d, {}
    d["span_h"] = (d["end"] - d["start"]) / 3600
    paid = float(d["span_h"].sum() + len(d) * 2 * signon_min / 60)
    summary = dict(
        pieces=len(d),
        drive_h=round(float(d["drive_h"].sum()), 1),
        paid_h=round(paid, 1),
        violations=int(d["violation"].sum()),
        min_drivers=int(np.ceil(paid / (max_duty_h * 0.85))),
        max_piece_h=round(float(d["span_h"].max()), 1),
    )
    for c in ("start", "end"):
        d[c] = d[c].map(lambda s_: f"{int(s_ // 3600):02d}:{int(s_ % 3600 // 60):02d}")
    return d, summary
