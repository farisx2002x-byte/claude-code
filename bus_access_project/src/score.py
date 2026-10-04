"""الدرجة والمستوى لكل مركبة + المركبة الموصى بها + نقاط التجميع + ربط المدرسة."""
import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

import config as C

LEVELS = ["سهل", "متوسط", "صعب"]
REC_AR = {"large": "باص كبير", "medium": "باص متوسط", "small": "فان", "pickup": "نقطة تجميع / ترتيب خاص"}


def step_pts(v, steps, top):
    for lim, pts in steps:
        if v <= lim:
            return pts
    return top


def zone_points(zone):
    z = str(zone or "")
    if z in C.ZONE_PTS:
        return C.ZONE_PTS[z]
    for k, p in C.ZONE_PTS_CONTAINS.items():
        if k in z:
            return p
    if any(k in z for k in C.ZONE_PTS_1):
        return 1
    return 0


def score_one(r, vk, zone, in_unknown, stage):
    """درجة طالب لمركبة. r = dict بقيم الأعمدة بدون اللاحقة. يرجع (level, score, walk_used, reasons, conf)."""
    V = C.VEHICLES[vk]
    young = stage in ("ابتدائي", "طفولة مبكرة")
    if not r["access"]:
        return "صعب", np.nan, np.nan, f"ما فيه وصول لـ{V['name']} (ما يوجد طريق مناسب لحجمه قريب من البيت)", "منخفضة"
    snap = r["snap_m"]
    net = r["walk_net_m"]
    walk = net if in_unknown else net + max(snap - C.WALK_FREE_M, 0)
    walk_used = walk * (C.YOUNG_FACTOR if young else 1.0)
    reasons = []
    pts = 0
    wp = step_pts(walk_used, C.WALK_STEPS, C.WALK_TOP_PTS)
    pts += wp
    if walk > C.WALK_FREE_M:
        reasons.append(f"يمشي {walk:.0f} م لأقرب نقطة يوصلها {V['name']}")
    b = r["bottleneck_row"]
    if np.isfinite(b):
        w = V["score_w"]
        rp = 0 if b >= w[0] else 1 if b >= w[1] else 2 if b >= w[2] else 3
        pts += rp
        if rp:
            reasons.append(f"أضيق شارع في الطريق {b:.0f} م تقريباً (بين حدود القطع)")
    t1, t2 = int(r["tight_turns"]), int(r["vtight_turns"])
    tp = min(t1 + 2 * t2, C.TURN_PTS_CAP)
    pts += tp
    if t1 + t2:
        reasons.append(f"{t1 + t2} التفاف حاد في شوارع ضيقة")
    rev = r["reverse_m"]
    if rev > 0:
        pts += step_pts(rev, C.REVERSE_STEPS, C.REVERSE_TOP)
        reasons.append(f"شارع مسدود بدون مكان دوران: الباص يرجع على الخلف {rev:.0f} م")
    nl = r["narrow_len_m"]
    npt = 0 if nl <= C.NARROW_LEN_STEPS[0][0] else 1 if nl <= C.NARROW_LEN_STEPS[1][0] else 2
    pts += npt
    if npt:
        reasons.append(f"يسير {nl:.0f} م داخل شوارع أضيق من {V['narrow']} م")
    zp = zone_points(zone)
    pts += zp
    if zp:
        reasons.append(f"المنطقة: {zone}")
    level = "سهل" if pts < C.LEVEL_CUTS[0] else "متوسط" if pts < C.LEVEL_CUTS[1] else "صعب"
    if walk_used > C.HARD_WALK_M:
        level = "صعب"
    conf = "منخفضة" if (in_unknown or snap > C.CONF_LOW_SNAP) else "متوسطة" if snap > C.CONF_MID_SNAP else "عالية"
    if in_unknown:
        reasons.append("تنبيه: مخطط البيت في البيانات بدون تفاصيل شوارع، النتيجة تقديرية")
    if not reasons:
        reasons.append("الباص يوصل لباب البيت بدون عوائق مرصودة")
    return level, float(pts), float(walk_used), "، ".join(reasons), conf


def attach_geo(raw, parcels, districts):
    """المنطقة (LU_ZONE) والحي لكل طالب بالـ sjoin."""
    pts = gpd.GeoDataFrame({"idx": raw["idx"]}, geometry=gpd.points_from_xy(raw.x, raw.y), crs=C.CRS_UTM)
    z = gpd.sjoin(pts, parcels[["LU_ZONE", "geometry"]], how="left", predicate="within")
    z = z[~z.index.duplicated()].set_index("idx")["LU_ZONE"]
    d = gpd.sjoin(pts, districts[["ARNAME", "geometry"]], how="left", predicate="within")
    d = d[~d.index.duplicated()].set_index("idx")["ARNAME"]
    raw = raw.copy()
    raw["zone"] = raw["idx"].map(z).fillna("")
    raw["district"] = raw["idx"].map(d).fillna("غير محدد")
    return raw


def score_all(raw):
    """يضيف level_X, score_X, walk_used_X, reasons_X, conf_X لكل مركبة + rec_vehicle."""
    df = raw.copy()
    zone = df["zone"].values if "zone" in df else np.array([""] * len(df))
    for vk in C.VEH_ORDER:
        s = C.VEHICLES[vk]["suffix"]
        cols = {c: df[f"{c}_{s}"].values for c in
                ("access", "snap_m", "walk_net_m", "bottleneck_row", "tight_turns", "vtight_turns",
                 "reverse_m", "narrow_len_m")}
        out = []
        for i in range(len(df)):
            r = {k: (v[i] if k != "access" else bool(v[i])) for k, v in cols.items()}
            out.append(score_one(r, vk, zone[i], bool(df["in_unknown"].iat[i]), df["stage"].iat[i]))
        o = pd.DataFrame(out, columns=["level", "score", "walk_used", "reasons", "conf"], index=df.index)
        for c in o:
            df[f"{c}_{s}"] = o[c]
    df["rec_vehicle"] = _recommend_vec(df)
    df["rec_vehicle_ar"] = df["rec_vehicle"].map(REC_AR)
    # أعمدة الكبير بأسمائها الأصلية
    for c in ("level", "score", "walk_used", "reasons", "conf"):
        df[c] = df[f"{c}_L"]
    return df


def recommend(row):
    for want in ("سهل", "متوسط"):
        for vk in C.VEH_ORDER:
            if row[f"level_{C.VEHICLES[vk]['suffix']}"] == want:
                return vk
    return "pickup"


def _recommend_vec(df):
    rec = np.full(len(df), "pickup", dtype=object)
    done = np.zeros(len(df), bool)
    for want in ("سهل", "متوسط"):
        for vk in C.VEH_ORDER:
            m = (df[f"level_{C.VEHICLES[vk]['suffix']}"].values == want) & ~done
            rec[m] = vk
            done |= m
    return rec


def build_pickups(df, vk="large"):
    """نقاط التجميع للطلاب اللي مشيهم أكثر من 50 م. يربط pickup_id عن طريق رقم المجموعة الأصلي."""
    s = C.VEHICLES[vk]["suffix"]
    m = (df[f"walk_used_{s}"] > C.PICKUP_MIN_WALK) & df[f"access_{s}"].fillna(False).astype(bool)
    sub = df[m]
    df = df.copy()
    df["pickup_id"] = np.nan
    df["pickup_x"] = np.nan
    df["pickup_y"] = np.nan
    if len(sub) == 0:
        return df, pd.DataFrame(columns=["pickup_id", "x", "y", "students", "hard", "max_walk", "schools", "district"])
    xy = sub[[f"stop_x_{s}", f"stop_y_{s}"]].to_numpy(float)
    tree = cKDTree(xy)
    pairs = np.array(sorted(tree.query_pairs(C.PICKUP_CLUSTER_M)))
    n = len(xy)
    if len(pairs):
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, cl = connected_components(g, directed=False)
    else:
        cl = np.arange(n)
    rows = []
    for c in np.unique(cl):
        mem = np.where(cl == c)[0]
        ctr = xy[mem].mean(axis=0)
        best = mem[np.argmin(np.linalg.norm(xy[mem] - ctr, axis=1))]
        pid = len(rows) + 1
        ss = sub.iloc[mem]
        rows.append(dict(pickup_id=pid, x=xy[best, 0], y=xy[best, 1], students=len(mem),
                         hard=int((ss[f"level_{s}"] == "صعب").sum()), max_walk=float(ss[f"walk_used_{s}"].max()),
                         schools="، ".join(sorted(set(ss["school"]))), district=ss["district"].mode().iat[0]
                         if "district" in ss and len(ss) else "", _cl=c))
    pk = pd.DataFrame(rows)
    cl2pid = dict(zip(pk["_cl"], pk["pickup_id"]))
    pid_arr = np.array([cl2pid[c] for c in cl])          # بالرقم الأصلي للمجموعة، مو بترتيب الصفوف
    px = pk.set_index("pickup_id")
    df.loc[sub.index, "pickup_id"] = pid_arr
    df.loc[sub.index, "pickup_x"] = px.loc[pid_arr, "x"].values
    df.loc[sub.index, "pickup_y"] = px.loc[pid_arr, "y"].values
    return df, pk.drop(columns="_cl")


def attach_board_point(df):
    """مكان الركوب: وقفة المركبة الموصى بها، أو نقطة التجميع."""
    bx = np.full(len(df), np.nan); by = bx.copy()
    for vk in C.VEH_ORDER:
        s = C.VEHICLES[vk]["suffix"]
        m = (df["rec_vehicle"] == vk).values
        bx[m], by[m] = df[f"stop_x_{s}"].values[m], df[f"stop_y_{s}"].values[m]
    m = (df["rec_vehicle"] == "pickup").values
    px, py = df["pickup_x"].values, df["pickup_y"].values
    bx[m], by[m] = px[m], py[m]
    # طلاب نقطة التجميع بدون pickup: وقفة أي مركبة وصلتهم
    miss = m & np.isnan(bx)
    for vk in ("large", "medium", "small"):
        s = C.VEHICLES[vk]["suffix"]
        f = miss & np.isnan(bx) & df[f"access_{s}"].fillna(False).astype(bool).values
        bx[f], by[f] = df[f"stop_x_{s}"].values[f], df[f"stop_y_{s}"].values[f]
    df = df.copy()
    df["board_x"], df["board_y"] = bx, by
    return df


def link_schools(df, schools, lookup):
    """يربط مدرسة الطالب بالاسم الرسمي وموقعها."""
    lk = dict(zip(lookup["student_school"], lookup["official_name"]))
    mt = dict(zip(lookup["student_school"], lookup["match"]))
    df = df.copy()
    df["school_official"] = df["school"].map(lk).fillna("")
    df["school_match"] = df["school"].map(mt).fillna("none")
    sc = schools.set_index("name")
    df["school_x"] = df["school_official"].map(sc["x"])
    df["school_y"] = df["school_official"].map(sc["y"])
    df["dist_school_m"] = np.hypot(df.x - df.school_x, df.y - df.school_y)
    return df
