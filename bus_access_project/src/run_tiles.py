"""تشغيل المحرك على المربعات بالتوازي مع كاش لكل مربع."""
import hashlib
import pickle
from multiprocessing import Pool

import geopandas as gpd
import numpy as np
import pandas as pd

import config as C
from src import tile_engine as TE

_G = {}
RES_COLS = ["access", "snap_m", "direct", "walk_net_m", "bottleneck_row", "tight_turns", "vtight_turns",
            "reverse_m", "narrow_len_m", "route_len_m", "stop_x", "stop_y"]


def _param_hash():
    keys = ["TILE", "HALO", "RES", "BIG_POLY_M2", "OPEN_EDT", "ASSUMED_WIDTH", "VEHICLES", "END_TRIM_M",
            "SPUR_EXTRA", "ISOLATED_MIN", "MAJOR_P10", "MAJOR_LEN", "TURN_DIR_M", "PEN_FACTORS"]
    s = repr([getattr(C, k) for k in keys]) + C.VERSION
    return hashlib.md5(s.encode()).hexdigest()[:8]


def tile_of(x, y):
    return int(np.floor(x / C.TILE)), int(np.floor(y / C.TILE))


def tile_list(students, schools):
    t = {tile_of(x, y) for x, y in zip(students.x, students.y)}
    for x, y in zip(schools.x, schools.y):
        i, j = tile_of(x, y)
        for di in range(-C.SCHOOL_TILE_RING, C.SCHOOL_TILE_RING + 1):
            for dj in range(-C.SCHOOL_TILE_RING, C.SCHOOL_TILE_RING + 1):
                t.add((i + di, j + dj))
    return sorted(t)


def _init():
    _G["polys"] = gpd.read_parquet(C.WORK / "parcels.parquet")
    _G["roads"] = gpd.read_parquet(C.WORK / "roads.parquet")
    _G["students"] = pd.read_parquet(C.WORK / "students.parquet")
    _G["polys"].sindex
    _G["roads"].sindex


def _cache_path(t):
    d = C.WORK / "tiles"
    d.mkdir(exist_ok=True)
    return d / f"{_param_hash()}_{t[0]}_{t[1]}.pkl"


def process_tile(t):
    cp = _cache_path(t)
    if cp.exists():
        return t, pickle.loads(cp.read_bytes())
    if not _G:
        _init()
    core = (t[0] * C.TILE, t[1] * C.TILE, (t[0] + 1) * C.TILE, (t[1] + 1) * C.TILE)
    st = _G["students"]
    m = (st.x >= core[0]) & (st.x < core[2]) & (st.y >= core[1]) & (st.y < core[3])
    stu = st[m]
    xy = stu[["x", "y"]].to_numpy(float)
    S = TE.build_streets(_G["polys"], _G["roads"], core)
    out = {"idx": stu["idx"].to_numpy(), "res": {}, "obst": [], "streets": None}
    out["in_unknown"] = S.unknown_at(xy)
    reach = {}
    for vk in C.VEH_ORDER:
        res, obs, rs = TE.analyze_vehicle(S, vk, xy)
        out["res"][vk] = res
        out["obst"] += obs
        reach[vk] = rs
    # المقاطع في قلب المربع فقط
    rows = []
    for k in range(S.n_seg):
        g = S.geoms[k]
        mid = g[len(g) // 2]
        if core[0] <= mid[0] < core[2] and core[1] <= mid[1] < core[3]:
            rows.append(dict(tile=f"{t[0]}_{t[1]}", coords=g, length=S.length[k], p10=S.p10[k],
                             med=S.med[k], assumed=S.assumed[k], is_major=bool(S.is_major[k]),
                             reach_L=bool(reach["large"][k]), reach_M=bool(reach["medium"][k]),
                             reach_S=bool(reach["small"][k])))
    out["streets"] = rows
    cp.write_bytes(pickle.dumps(out))
    return t, out


def run(students, schools, workers=None, fresh=False):
    workers = workers or C.WORKERS
    tiles = tile_list(students, schools)
    if fresh:
        for p in (C.WORK / "tiles").glob("*.pkl"):
            p.unlink()
    print(f"عدد المربعات: {len(tiles)}")
    outs = []
    if workers > 1:
        with Pool(workers, initializer=_init) as pool:
            for k, (t, o) in enumerate(pool.imap_unordered(process_tile, tiles), 1):
                outs.append(o)
                if k % 20 == 0 or k == len(tiles):
                    print(f"  {k}/{len(tiles)}", flush=True)
    else:
        for k, t in enumerate(tiles, 1):
            outs.append(process_tile(t)[1])
            if k % 20 == 0:
                print(f"  {k}/{len(tiles)}", flush=True)
    return merge(outs, students)


def merge(outs, students):
    """يجمع نتائج المربعات: جدول الطلاب الخام (أعمدة لكل مركبة بلاحقة)، الشوارع، العوائق."""
    frames = []
    for o in outs:
        if len(o["idx"]) == 0:
            continue
        d = {"idx": o["idx"], "in_unknown": o["in_unknown"]}
        for vk in C.VEH_ORDER:
            sfx = C.VEHICLES[vk]["suffix"]
            for c in RES_COLS:
                d[f"{c}_{sfx}"] = o["res"][vk][c]
        frames.append(pd.DataFrame(d))
    raw = students.merge(pd.concat(frames), on="idx", how="left")
    streets = [r for o in outs for r in o["streets"]]
    obst = pd.DataFrame([r for o in outs for r in o["obst"]])
    return raw, pd.DataFrame(streets), obst
