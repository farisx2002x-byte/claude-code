"""قلب التحليل: قياس عرض الشوارع من الفراغ بين القطع، وتحليل كل مركبة (لكل مربع).

الفكرة: الفراغ بين القطع = حرم الشارع (ROW). نحوله لراستر 1 م، نأخذ EDT والـ skeleton،
ونقسمه لمقاطع (skan) ثم نحلل وصول كل مركبة بحدودها.
"""
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd
from rasterio import features
from rasterio.transform import from_origin
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import box
from skan import Skeleton, summarize
from skimage.morphology import disk, skeletonize

import config as C

PIX_STEP = 2  # نأخذ كل بكسل ثاني من محور الشارع لربط الطلاب


@dataclass
class Streets:
    """شبكة الشوارع المقاسة لمربع واحد (قبل تحليل المركبات)."""
    x0: float
    y1: float
    node_xy: np.ndarray            # (n,2)
    node_edt: np.ndarray           # (n,)
    src: np.ndarray
    dst: np.ndarray
    length: np.ndarray
    p10: np.ndarray
    med: np.ndarray
    assumed: np.ndarray
    major_frac: np.ndarray
    is_major: np.ndarray
    dir_src: np.ndarray            # (m,2) اتجاه الخارج من src داخل المقطع
    dir_dst: np.ndarray
    geoms: list = field(default_factory=list)   # إحداثيات مبسطة لكل مقطع (UTM)
    pix_xy: np.ndarray = None      # نقاط محور الشارع لربط الطلاب
    pix_seg: np.ndarray = None
    pix_pos: np.ndarray = None     # المسافة من src لين النقطة
    unk: np.ndarray = None         # راستر القطع المجهولة (للتحقق من موقع البيت)
    core: tuple = None

    @property
    def n_seg(self):
        return len(self.src)

    def unknown_at(self, xy):
        if self.unk is None or len(xy) == 0:
            return np.zeros(len(xy), bool)
        c = ((xy[:, 0] - self.x0) / C.RES).astype(int)
        r = ((self.y1 - xy[:, 1]) / C.RES).astype(int)
        ok = (r >= 0) & (r < self.unk.shape[0]) & (c >= 0) & (c < self.unk.shape[1])
        out = np.zeros(len(xy), bool)
        out[ok] = self.unk[r[ok], c[ok]]
        return out


def _empty_streets(x0, y1, core):
    z = np.zeros(0)
    z2 = np.zeros((0, 2))
    return Streets(x0, y1, z2, z, z.astype(int), z.astype(int), z, z, z, z, z, z.astype(bool),
                   z2, z2, [], z2, z.astype(int), z, None, core)


def _sel(gdf, bbox):
    if gdf is None or len(gdf) == 0:
        return gdf
    idx = gdf.sindex.query(box(*bbox), predicate="intersects")
    return gdf.iloc[idx]


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else np.array([1.0, 0.0])


def build_streets(polys, roads, core):
    """core = (minx, miny, maxx, maxy) بالمتر UTM. polys: القطع (LU_ZONE, geometry). roads: خطوط OSM (fclass)."""
    minx, miny, maxx, maxy = core
    ext = (minx - C.HALO, miny - C.HALO, maxx + C.HALO, maxy + C.HALO)
    x0, y1 = np.floor(ext[0]), np.ceil(ext[3])
    W = int(np.ceil((ext[2] - x0) / C.RES))
    H = int(np.ceil((y1 - ext[1]) / C.RES))
    tr = from_origin(x0, y1, C.RES, C.RES)

    P = _sel(polys, ext)
    if P is not None and len(P):
        area = P.geometry.area.values
        zone = P["LU_ZONE"].astype(str).values if "LU_ZONE" in P else np.array([""] * len(P))
        parking = np.array([any(w in z for w in C.PARKING_WORDS) for z in zone])
        small = P.geometry.values[(area <= C.BIG_POLY_M2) & ~parking]
        big = P.geometry.values[area > C.BIG_POLY_M2]
    else:
        small, big = [], []

    def rast(geoms, dtype="uint8"):
        if len(geoms) == 0:
            return np.zeros((H, W), bool)
        return features.rasterize([(g, 1) for g in geoms], out_shape=(H, W), transform=tr,
                                  fill=0, dtype=dtype).astype(bool)

    obst, unk = rast(small), rast(big)

    # طرق OSM: مفترضة العرض حسب الفئة
    R = _sel(roads, ext)
    roadall = np.zeros((H, W), bool)
    majbuf = np.zeros((H, W), bool)
    if R is not None and len(R):
        fc = R["fclass"].astype(str).values
        wid = np.array([C.ASSUMED_WIDTH.get(f, 0) for f in fc], float)
        order = np.argsort(wid)
        shapes = [(R.geometry.values[i].buffer(wid[i] / 2.0), 1) for i in order if wid[i] > 0]
        if shapes:
            roadall = features.rasterize(shapes, out_shape=(H, W), transform=tr, fill=0,
                                         dtype="uint8").astype(bool)
        maj = [R.geometry.values[i].buffer(C.MAJOR_BUFFER_M) for i in range(len(R)) if fc[i] in C.MAJOR_FCLASS]
        if maj:
            majbuf = rast(maj)

    if not (obst.any() or unk.any()):
        return _empty_streets(x0, y1, core)
    blocked = obst | (unk & ~roadall)
    free = ~blocked
    d_poly = ndi.distance_transform_edt(~(obst | unk))
    openland = (d_poly > C.OPEN_EDT) & ~roadall
    free &= ~openland
    free = ndi.binary_opening(free, structure=disk(1))
    assumed_mask = roadall & (unk | (d_poly > C.OPEN_EDT))

    if not free.any():
        return _empty_streets(x0, y1, core)
    edt = ndi.distance_transform_edt(free)
    skel = skeletonize(free)
    if not skel.any():
        return _empty_streets(x0, y1, core)

    sk = Skeleton(skel, spacing=1)
    summ = summarize(sk, separator="_")

    nodekey, nodes = {}, []

    def nid(r, c):
        k = (int(r), int(c))
        if k not in nodekey:
            nodekey[k] = len(nodes)
            nodes.append(k)
        return nodekey[k]

    segs = []
    for i in range(len(summ)):
        row = summ.iloc[i]
        rc = sk.path_coordinates(i).astype(int)
        if len(rc) < 2:
            continue
        a = nid(row["image_coord_src_0"], row["image_coord_src_1"])
        b = nid(row["image_coord_dst_0"], row["image_coord_dst_1"])
        if a == b:
            continue
        segs.append((a, b, rc))

    segs = _prune(segs, nodes, edt)
    if not segs:
        return _empty_streets(x0, y1, core)

    # إعادة ترقيم العقد بعد التقليم
    used = sorted({s[0] for s in segs} | {s[1] for s in segs})
    remap = {o: i for i, o in enumerate(used)}
    node_rc = np.array([nodes[o] for o in used])
    node_xy = np.column_stack([x0 + (node_rc[:, 1] + 0.5) * C.RES, y1 - (node_rc[:, 0] + 0.5) * C.RES])
    node_edt = edt[node_rc[:, 0], node_rc[:, 1]]

    m = len(segs)
    src = np.zeros(m, int); dst = np.zeros(m, int)
    length = np.zeros(m); p10 = np.zeros(m); med = np.zeros(m)
    assumed = np.zeros(m); majf = np.zeros(m)
    dsrc = np.zeros((m, 2)); ddst = np.zeros((m, 2))
    geoms = []
    px, ps, pp = [], [], []
    for k, (a, b, rc) in enumerate(segs):
        src[k], dst[k] = remap[a], remap[b]
        xy = np.column_stack([x0 + (rc[:, 1] + 0.5) * C.RES, y1 - (rc[:, 0] + 0.5) * C.RES])
        step = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        cum = np.concatenate([[0], np.cumsum(step)])
        L = cum[-1]
        length[k] = L
        w = 2 * edt[rc[:, 0], rc[:, 1]]
        keep = (cum >= C.END_TRIM_M) & (cum <= L - C.END_TRIM_M)
        wt = w[keep] if keep.sum() >= 3 else w
        p10[k] = np.percentile(wt, 10)
        med[k] = np.median(w)
        assumed[k] = assumed_mask[rc[:, 0], rc[:, 1]].mean()
        majf[k] = majbuf[rc[:, 0], rc[:, 1]].mean()
        i1 = min(np.searchsorted(cum, C.TURN_DIR_M), len(xy) - 1)
        dsrc[k] = _unit(xy[i1] - xy[0])
        i2 = max(np.searchsorted(cum, L - C.TURN_DIR_M) , 0)
        ddst[k] = _unit(xy[i2] - xy[-1])
        sel = np.unique(np.concatenate([np.arange(0, len(xy), 5), [len(xy) - 1]]))
        geoms.append(xy[sel])
        idx = np.unique(np.concatenate([np.arange(0, len(xy), PIX_STEP), [len(xy) - 1]]))
        px.append(xy[idx]); ps.append(np.full(len(idx), k)); pp.append(cum[idx])

    is_major = (p10 >= C.MAJOR_P10) & (length >= C.MAJOR_LEN) & (assumed < 0.5) & (med < C.MAJOR_MED_MAX)
    # الطريق الرئيسي من OSM (مقاس أو مفترض) يعتبر رئيسي لو أغلب طوله داخل buffer الرئيسية
    return Streets(x0, y1, node_xy, node_edt, src, dst, length, p10, med, assumed, majf, is_major,
                   dsrc, ddst, geoms, np.vstack(px), np.concatenate(ps), np.concatenate(pp), unk, core)


def _prune(segs, nodes, edt):
    """تقليم الفروع الزائدة (مرتين)."""
    for _ in range(2):
        deg = {}
        for a, b, _rc in segs:
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
        out = []
        for a, b, rc in segs:
            L = np.sum(np.linalg.norm(np.diff(rc, axis=0), axis=1))
            da, db = deg[a], deg[b]
            drop = False
            if da == 1 and db == 1:
                drop = L < C.ISOLATED_MIN
            elif (da == 1 and db >= 3) or (db == 1 and da >= 3):
                j = b if da == 1 else a
                drop = L < edt[nodes[j][0], nodes[j][1]] + C.SPUR_EXTRA
            if not drop:
                out.append((a, b, rc))
        if len(out) == len(segs):
            break
        segs = out
    return segs


# ───────────────────────── تحليل المركبة ─────────────────────────

def _pen(p10, pen):
    return np.where(p10 >= pen[0], C.PEN_FACTORS[0], np.where(p10 >= pen[1], C.PEN_FACTORS[1],
                    np.where(p10 >= pen[2], C.PEN_FACTORS[2], C.PEN_FACTORS[3])))


def turn_class(S, V, node, sa, sb):
    """0 لا شيء، 1 حاد، 2 حاد جداً عند العقدة بين المقطعين sa و sb."""
    if S.node_edt[node] >= V["turn_room"]:
        return 0
    oa = S.dir_src[sa] if S.src[sa] == node else S.dir_dst[sa]
    ob = S.dir_src[sb] if S.src[sb] == node else S.dir_dst[sb]
    ang = np.degrees(np.arccos(np.clip(np.dot(oa, ob), -1, 1)))
    dev = 180 - ang
    tot = S.p10[sa] + S.p10[sb]
    if (dev >= C.TURN_VSHARP_DEG and tot < V["sharp_sum"]) or (dev >= C.TURN_SHARP_DEG and tot < V["vsharp_sum"]):
        return 2
    if dev >= C.TURN_SHARP_DEG and tot < V["sharp_sum"]:
        return 1
    return 0


def _csr(n, u, v, w):
    return coo_matrix((np.concatenate([w, w]), (np.concatenate([u, v]), np.concatenate([v, u]))),
                      shape=(n, n)).tocsr()


def _best_edges(u, v, w, ids):
    """أرخص مقطع لكل زوج عقد (ومعه علامة الأزواج المتوازية = حلقة)."""
    best, par = {}, set()
    for a, b, c, i in zip(u, v, w, ids):
        k = (a, b) if a < b else (b, a)
        if k in best:
            par.add(k)
            if c < best[k][0]:
                best[k] = (c, i)
        else:
            best[k] = (c, i)
    return best, par


def analyze_vehicle(S, vk, stu_xy):
    """يرجع (جدول نتائج الطلاب، عوائق، reach لكل مقطع)."""
    V = C.VEHICLES[vk]
    N = len(stu_xy)
    res = dict(access=np.zeros(N, bool), snap_m=np.full(N, np.nan), direct=np.zeros(N, bool),
               walk_net_m=np.full(N, np.nan), bottleneck_row=np.full(N, np.nan),
               tight_turns=np.zeros(N, int), vtight_turns=np.zeros(N, int),
               reverse_m=np.zeros(N), narrow_len_m=np.zeros(N), route_len_m=np.zeros(N),
               stop_x=np.full(N, np.nan), stop_y=np.full(N, np.nan))
    obstacles = []
    if S.n_seg == 0 or N == 0:
        return res, obstacles, np.zeros(S.n_seg, bool)

    n = len(S.node_xy)
    # snap الطلاب لمحور الشارع
    tree = cKDTree(S.pix_xy)
    snap, pi = tree.query(stu_xy)
    sseg, spos = S.pix_seg[pi], S.pix_pos[pi]
    res["snap_m"] = snap

    allowed = S.p10 >= V["min_row"]
    cost = S.length * _pen(S.p10, V["pen"])
    seeds = np.unique(np.concatenate([S.src[S.is_major & allowed], S.dst[S.is_major & allowed]]))

    ids = np.where(allowed)[0]
    dist = np.full(n, np.inf)
    pred = np.full(n, -9999)
    if len(seeds) and len(ids):
        best, par = _best_edges(S.src[ids], S.dst[ids], cost[ids], ids)
        ks = list(best.keys())
        bu = np.array([k[0] for k in ks]); bv = np.array([k[1] for k in ks])
        bw = np.array([best[k][0] for k in ks]); bseg = np.array([best[k][1] for k in ks])
        G = _csr(n, bu, bv, np.maximum(bw, 1e-6))
        dist, pred, _srcs = dijkstra(G, directed=False, indices=seeds, min_only=True,
                                     return_predecessors=True)
        edge_seg = {}
        for a, b, s in zip(bu, bv, bseg):
            edge_seg[(a, b)] = s
            edge_seg[(b, a)] = s
    else:
        edge_seg, par, bu, bv = {}, set(), np.zeros(0, int), np.zeros(0, int)

    reached = np.isfinite(dist)
    reach_seg = allowed & (reached[S.src] | reached[S.dst])
    if not reached.any():
        return res, obstacles, reach_seg

    # العقد الآمنة ومناطق التمرير (ثنائية الاتصال بالحواف)
    seedset = set(seeds.tolist())
    Gx = nx.Graph()
    rn = np.where(reached)[0]
    Gx.add_nodes_from(rn.tolist())
    for a, b in zip(bu, bv):
        if reached[a] and reached[b]:
            Gx.add_edge(int(a), int(b))
    bridges = {tuple(sorted(e)) for e in nx.bridges(Gx)}
    H = Gx.copy()
    H.remove_edges_from(list(bridges))
    comp = {}
    comps = list(nx.connected_components(H))
    safe_comp = []
    for ci, cs in enumerate(comps):
        for x in cs:
            comp[x] = ci
        sf = len(cs) > 1 or any((x in seedset) or S.node_edt[x] >= V["turnaround"] for x in cs)
        sf = sf or any(tuple(sorted((x, y))) in par for x in cs for y in Gx[x])
        safe_comp.append(sf)
    T = nx.Graph()
    T.add_nodes_from(range(len(comps)))
    for a, b in bridges:
        T.add_edge(comp[a], comp[b])
    sub_safe = list(safe_comp)
    seen = set()
    for r0 in range(len(comps)):
        if r0 in seen:
            continue
        cc = nx.node_connected_component(T, r0)
        root = next((c for c in cc if any(x in seedset for x in comps[c])), r0)
        seen |= cc
        order = list(nx.dfs_preorder_nodes(T, root))
        parent = nx.dfs_predecessors(T, root)
        for c in reversed(order):
            if c in parent and sub_safe[c]:
                sub_safe[parent[c]] = True
    pt = np.zeros(n, bool)
    for x in rn:
        pt[x] = sub_safe[comp[int(x)]]

    # DP على شجرة أقصر الطرق
    order = rn[np.argsort(dist[rn])]
    plen = np.zeros(n); bott = np.full(n, np.inf); tight = np.zeros(n, int); vtight = np.zeros(n, int)
    narrow = np.zeros(n); lastpt = np.zeros(n); revn = np.zeros(n)
    pseg = np.full(n, -1)
    turn_at = {}
    for x in order:
        p = pred[x]
        if p < 0:
            lastpt[x] = 0.0
            continue
        s = edge_seg[(p, x)]
        pseg[x] = s
        plen[x] = plen[p] + S.length[s]
        bott[x] = min(bott[p], S.p10[s])
        narrow[x] = narrow[p] + (S.length[s] if S.p10[s] < V["narrow"] else 0)
        tight[x], vtight[x] = tight[p], vtight[p]
        if pseg[p] >= 0:
            t = turn_class(S, V, p, pseg[p], s)
            if t == 1:
                tight[x] += 1
            elif t == 2:
                vtight[x] += 1
            if t:
                turn_at[x] = (p, t)
        lastpt[x] = plen[x] if pt[x] else lastpt[p]
        revn[x] = plen[x] - lastpt[x]

    # الوصول لكل طالب
    walk_nodes = None
    for i in range(N):
        s = sseg[i]
        a, b, L, o = S.src[s], S.dst[s], S.length[s], spos[i]
        cand = []
        if allowed[s]:
            for node, off, other in ((a, o, b), (b, L - o, a)):
                if reached[node] and pseg[node] != s:
                    cand.append((dist[node] + off, node, off, other))
        if cand:
            _, node, off, other = min(cand)
            res["direct"][i] = True
            res["walk_net_m"][i] = 0.0
            res["bottleneck_row"][i] = min(bott[node], S.p10[s])
            res["tight_turns"][i], res["vtight_turns"][i] = tight[node], vtight[node]
            rev = revn[node] + (off if not pt[other] else 0)
            res["reverse_m"][i] = rev
            res["narrow_len_m"][i] = narrow[node] + (off if S.p10[s] < V["narrow"] else 0)
            res["route_len_m"][i] = plen[node] + off
            res["stop_x"][i], res["stop_y"][i] = S.pix_xy[pi[i]]
            res["access"][i] = True
        else:
            if walk_nodes is None:
                allids = np.arange(S.n_seg)
                wb, _ = _best_edges(S.src, S.dst, S.length, allids)
                wk = list(wb.keys())
                Gw = _csr(n, np.array([k[0] for k in wk]), np.array([k[1] for k in wk]),
                          np.array([wb[k][0] for k in wk]))
                srcs = np.where(reached)[0]
                wd, _, wsrc = dijkstra(Gw, directed=False, indices=srcs, min_only=True,
                                       return_predecessors=True)
                walk_nodes = (wd, wsrc)
            wd, wsrc = walk_nodes
            opts = [(wd[a] + o, a), (wd[b] + L - o, b)]
            w, node = min(opts)
            if not np.isfinite(w):
                continue
            stop = wsrc[node]
            res["walk_net_m"][i] = w
            res["bottleneck_row"][i] = bott[stop]
            res["tight_turns"][i], res["vtight_turns"][i] = tight[stop], vtight[stop]
            res["reverse_m"][i] = revn[stop]
            res["narrow_len_m"][i] = narrow[stop]
            res["route_len_m"][i] = plen[stop]
            res["stop_x"][i], res["stop_y"][i] = S.node_xy[stop]
            res["access"][i] = True

    # عوائق على الطرق المستخدمة فعلاً
    used = np.zeros(n, bool)
    # علّم العقد المستخدمة (أقرب عقدة لوقفة كل طالب)
    if res["access"].any():
        sx = np.column_stack([res["stop_x"], res["stop_y"]])[res["access"]]
        _, nn = cKDTree(S.node_xy).query(sx)
        used[np.unique(nn)] = True
        for x in order[::-1]:
            if used[x] and pred[x] >= 0:
                used[pred[x]] = True
    cx0, cy0, cx1, cy1 = S.core
    deg = np.zeros(n, int)
    for a, b in zip(bu, bv):
        deg[a] += 1; deg[b] += 1
    for x, (p, t) in turn_at.items():
        if used[x]:
            px, py = S.node_xy[p]
            if cx0 <= px < cx1 and cy0 <= py < cy1:
                obstacles.append(dict(x=px, y=py, type="turn_vsharp" if t == 2 else "turn_sharp",
                                      veh=vk, reverse_m=0.0))
    for x in rn:
        if used[x] and deg[x] == 1 and not pt[x] and revn[x] > 0:
            px, py = S.node_xy[x]
            if cx0 <= px < cx1 and cy0 <= py < cy1:
                obstacles.append(dict(x=px, y=py, type="deadend", veh=vk, reverse_m=float(revn[x])))
    return res, obstacles, reach_seg
