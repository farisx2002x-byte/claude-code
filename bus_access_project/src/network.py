"""شبكة طرق متصلة لجدة: المقاطع المقاسة + عمود فقري OSM مع الاتجاه الواحد، وأزمنة السفر."""
import pickle

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

import config as C


def speed_kmh_measured(med, is_major):
    if is_major:
        return C.SPEED_MAJOR_MEASURED
    for lim, v in C.SPEED_BY_WIDTH:
        if med >= lim:
            return v
    return C.SPEED_NARROW


def _cluster(xy, tol):
    tree = cKDTree(xy)
    pairs = np.array(sorted(tree.query_pairs(tol)))
    n = len(xy)
    if len(pairs) == 0:
        return np.arange(n)
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    return connected_components(g, directed=False)[1]


class Network:
    def __init__(self, node_xy, eu, ev, elen, etime, erow, egid, edir, geoms):
        self.node_xy, self.u, self.v = node_xy, eu, ev
        self.length, self.time_s, self.row_min = elen, etime, erow
        self.gid, self.fwd = egid, edir      # fwd: الضلع بنفس اتجاه الهندسة
        self.geoms = geoms
        self._csr, self._main, self._tree = {}, {}, {}
        self._eidx = None

    @property
    def n(self):
        return len(self.node_xy)

    def graph(self, vk, weight="time"):
        """CSR للمركبة: المسموح = row_min ≥ min_row."""
        key = (vk, weight)
        if key not in self._csr:
            ok = self.row_min >= C.VEHICLES[vk]["min_row"]
            w = (self.time_s if weight == "time" else self.length)[ok]
            u, v = self.u[ok], self.v[ok]
            # نحتفظ بأرخص ضلع لكل زوج (coo→csr يجمع المكرر)
            df = pd.DataFrame({"u": u, "v": v, "w": np.maximum(w, 1e-6)}).groupby(["u", "v"], as_index=False).min()
            self._csr[key] = csr_matrix((df.w.values, (df.u.values, df.v.values)), shape=(self.n, self.n))
        return self._csr[key]

    def time_optimal_lengths(self, vk):
        """طول الضلع الأسرع لكل زوج (u,v): مفاتيح مرتبة u*n+v وأطوالها."""
        key = (vk, "tlen")
        if key not in self._csr:
            ok = self.row_min >= C.VEHICLES[vk]["min_row"]
            df = pd.DataFrame({"u": self.u[ok], "v": self.v[ok], "t": self.time_s[ok], "l": self.length[ok]})
            df = df.sort_values("t").drop_duplicates(["u", "v"])
            k = df.u.values.astype(np.int64) * self.n + df.v.values
            o = np.argsort(k)
            self._csr[key] = (k[o], df.l.values[o])
        return self._csr[key]

    def main_nodes(self, vk):
        """أكبر مكوّن متصل بقوة للمركبة."""
        if vk not in self._main:
            G = self.graph(vk, "length")
            _, lab = connected_components(G, directed=True, connection="strong")
            deg = np.diff(G.indptr) + np.bincount(G.indices, minlength=self.n)
            lab = np.where(deg > 0, lab, -1)
            big = np.bincount(lab[lab >= 0]).argmax() if (lab >= 0).any() else -1
            self._main[vk] = np.where(lab == big)[0]
        return self._main[vk]

    def snap(self, xy, vk, max_m=500):
        """أقرب عقدة في المكوّن الرئيسي. يرجع (node, dist)."""
        if vk not in self._tree:
            mn = self.main_nodes(vk)
            self._tree[vk] = (mn, cKDTree(self.node_xy[mn]))
        mn, t = self._tree[vk]
        d, i = t.query(np.asarray(xy, float))
        node = mn[i]
        return np.where(d <= max_m, node, -1), d

    def edge_lookup(self):
        if self._eidx is None:
            self._eidx = {}
            for k in np.argsort(-self.time_s):   # الأسرع يكتب أخيراً
                self._eidx[(self.u[k], self.v[k])] = k
        return self._eidx

    def path_geometry(self, nodes):
        """إحداثيات الخط على الشبكة لسلسلة عقد."""
        lk = self.edge_lookup()
        pts = []
        for a, b in zip(nodes[:-1], nodes[1:]):
            k = lk.get((a, b))
            if k is None:
                seg = np.array([self.node_xy[a], self.node_xy[b]])
            else:
                g = self.geoms[self.gid[k]]
                seg = g if self.fwd[k] else g[::-1]
            pts.append(seg)
        return np.vstack(pts) if pts else np.zeros((0, 2))

    def shortest(self, vk, sources, weight="time", reverse=False, min_only=False):
        G = self.graph(vk, weight)
        if reverse:
            G = G.T.tocsr()
        return dijkstra(G, directed=True, indices=sources, return_predecessors=True, min_only=min_only)

    def matrix(self, vk, src_nodes, dst_nodes, weight="time"):
        """مصفوفة أزمنة/أطوال بين مجموعتين من العقد، على دفعات (للذاكرة)."""
        G = self.graph(vk, weight)
        out = np.full((len(src_nodes), len(dst_nodes)), np.inf)
        for i in range(0, len(src_nodes), C.MATRIX_BATCH):
            d = dijkstra(G, directed=True, indices=src_nodes[i:i + C.MATRIX_BATCH])
            out[i:i + C.MATRIX_BATCH] = d[:, dst_nodes]
        return out

    def save(self, path):
        d = {k: v for k, v in self.__dict__.items() if k not in ("_csr", "_main", "_tree", "_eidx")}
        pickle.dump(d, open(path, "wb"))

    @staticmethod
    def load(path):
        d = pickle.load(open(path, "rb"))
        n = Network.__new__(Network)
        n.__dict__.update(d)
        n._csr, n._main, n._tree, n._eidx = {}, {}, {}, None
        return n


def build_network(streets, roads=None):
    """streets: جدول مقاطع المربعات (coords, length, p10, med, is_major). roads: خطوط OSM بـ UTM."""
    geoms = list(streets["coords"])
    ends = np.array([[g[0], g[-1]] for g in geoms])           # (m,2,2)
    ep = ends.reshape(-1, 2)
    lab = _cluster(ep, C.NET_SNAP_M)
    node_xy = np.array([ep[lab == k].mean(axis=0) for k in range(lab.max() + 1)])
    su, sv = lab[0::2], lab[1::2]

    U, V, L, T, R, G, F = [], [], [], [], [], [], []

    def add(u, v, length, kmh, row, gid, both=True, fwd_dir=True):
        t = length / (kmh * C.PEAK_FACTOR / 3.6)
        U.append(u); V.append(v); L.append(length); T.append(t); R.append(row); G.append(gid); F.append(fwd_dir)
        if both:
            U.append(v); V.append(u); L.append(length); T.append(t); R.append(row); G.append(gid); F.append(not fwd_dir)

    meas_row = np.zeros(len(node_xy))
    for k in range(len(geoms)):
        if su[k] == sv[k]:
            continue
        kmh = speed_kmh_measured(streets["med"].iat[k], bool(streets["is_major"].iat[k]))
        add(su[k], sv[k], float(streets["length"].iat[k]), kmh, float(streets["p10"].iat[k]), k)

    # وصل النهايات المقطوعة (درجة 1) بأقرب عقدة من مكوّن ثاني خلال 15 م
    nn = len(node_xy)
    deg = np.bincount(np.array(U), minlength=nn)
    A = coo_matrix((np.ones(len(U)), (U, V)), shape=(nn, nn)).tocsr()
    _, comp = connected_components(A, directed=False)
    tree = cKDTree(node_xy)
    for a in np.where(deg <= 1)[0]:
        if deg[a] == 0:
            continue
        for b in tree.query_ball_point(node_xy[a], C.NET_BRIDGE_M):
            if comp[b] != comp[a]:
                d = float(np.linalg.norm(node_xy[a] - node_xy[b]))
                geoms.append(np.array([node_xy[a], node_xy[b]]))
                add(a, b, max(d, 0.1), C.SPEED_NARROW, 10.0, len(geoms) - 1)
                break

    # عمود فقري من OSM مع الاتجاه الواحد
    extra_xy = []
    if roads is not None and len(roads):
        sel = roads[roads["fclass"].isin(C.SPEED_OSM)]
        osm_nodes = {}
        mt = cKDTree(node_xy)
        for geom, fc, ow in zip(sel.geometry, sel["fclass"], sel["oneway"] if "oneway" in sel else ["B"] * len(sel)):
            parts = geom.geoms if hasattr(geom, "geoms") else [geom]
            for part in parts:
                co = np.asarray(part.coords)
                ids = []
                for p in co:
                    key = (round(p[0], 1), round(p[1], 1))
                    if key not in osm_nodes:
                        osm_nodes[key] = nn + len(extra_xy)
                        extra_xy.append(p)
                    ids.append(osm_nodes[key])
                for i in range(len(ids) - 1):
                    if ids[i] == ids[i + 1]:
                        continue
                    seg = np.array([co[i], co[i + 1]])
                    geoms.append(seg)
                    d = float(np.linalg.norm(seg[1] - seg[0]))
                    row = float(C.ASSUMED_WIDTH.get(fc, 10))
                    kmh = C.SPEED_OSM[fc]
                    if ow == "T":
                        add(ids[i + 1], ids[i], d, kmh, row, len(geoms) - 1, both=False, fwd_dir=False)
                    elif ow == "F":
                        add(ids[i], ids[i + 1], d, kmh, row, len(geoms) - 1, both=False)
                    else:
                        add(ids[i], ids[i + 1], d, kmh, row, len(geoms) - 1)
        if extra_xy:
            exy = np.array(extra_xy)
            d, j = mt.query(exy, distance_upper_bound=C.OSM_LINK_M)
            for k in np.where(np.isfinite(d))[0]:
                geoms.append(np.array([exy[k], node_xy[j[k]]]))
                add(nn + k, j[k], max(float(d[k]), 0.1), C.SPEED_NARROW, 10.0, len(geoms) - 1)
            node_xy = np.vstack([node_xy, exy])
    return Network(node_xy, np.array(U), np.array(V), np.array(L), np.array(T), np.array(R),
                   np.array(G), np.array(F), geoms)


def school_times(net, df, schools_xy):
    """زمن ومسافة الطريق من وقفة كل طالب (بمركبته الموصى بها) لمدرسته. نشغّل Dijkstra معكوس من المدارس.
    schools_xy: dict اسم رسمي ← (x,y). يرجع عمودين: road_min, road_km."""
    tmin = np.full(len(df), np.nan)
    dkm = np.full(len(df), np.nan)
    for vk in C.VEH_ORDER:
        rec = df["rec_vehicle"].values
        m = (rec == vk) if vk != "large" else ((rec == "large") | (rec == "pickup"))
        m &= ~np.isnan(df["board_x"].values)
        if not m.any():
            continue
        Gt = net.graph(vk, "time")
        for sname, idx in df[m].groupby("school_official").groups.items():
            if sname not in schools_xy:
                continue
            snode, _ = net.snap([schools_xy[sname]], vk)
            if snode[0] < 0:
                continue
            d, pred = dijkstra(Gt.T.tocsr(), directed=True, indices=snode[0], return_predecessors=True)
            order = np.where(np.isfinite(d))[0]
            order = order[np.argsort(d[order])]
            ln = np.zeros(net.n)
            keys, lens = net.time_optimal_lengths(vk)
            xs = order[pred[order] >= 0]
            elen = lens[np.searchsorted(keys, xs.astype(np.int64) * net.n + pred[xs])]
            el = dict(zip(xs.tolist(), elen.tolist()))
            for x in order:
                p = pred[x]
                if p >= 0:
                    ln[x] = ln[p] + el[x]
            sub = df.loc[idx]
            nodes, _ = net.snap(sub[["board_x", "board_y"]].to_numpy(float), vk)
            ok = nodes >= 0
            pos = df.index.get_indexer(sub.index)
            tmin[pos[ok]] = d[nodes[ok]] / 60.0
            dkm[pos[ok]] = ln[nodes[ok]] / 1000.0
    return tmin, dkm
