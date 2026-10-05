"""شبكة الشوارع (OSM): قراءة من shapefile/GeoJSON/GPKG/Overpass، بناء رسم بياني بالاتجاه الواحد، وأزمنة ومسافات مشي وقيادة."""

import json
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from transport_hub.core.log import get_logger

log = get_logger("roadnet")

# سرعات القيادة الافتراضية (كم/س) حسب فئة الطريق؛ تُضرب بمعامل الذروة. maxspeed إن وُجد يتقدّم عليها.
DRIVE_KMH = {
    "motorway": 80,
    "trunk": 65,
    "primary": 50,
    "secondary": 42,
    "tertiary": 36,
    "unclassified": 32,
    "residential": 28,
    "living_street": 12,
    "service": 18,
    "track": 15,
    "road": 25,
}
PEAK_FACTOR = 0.8
WALK_EXCLUDED = {"motorway", "motorway_link", "trunk_link"}
MAX_SNAP_M = 300  # أبعد نقطة تُربط بالشبكة؛ ما بعدها تُعامل «غير مرتبطة» وتُقدَّر بالخط المستقيم
NODE_PRECISION = 0.5  # م: رؤوس أقرب من هذا تُدمج في عقدة واحدة


class RoadDataError(ValueError):
    """مشكلة في ملف الشوارع برسالة عربية."""


@dataclass
class Lines:
    """خطوط الشوارع بإحداثيات WGS84 (lon, lat) مع الفئة والاتجاه الواحد والسرعة."""

    coords: list
    fclass: list
    oneway: list = field(default_factory=list)
    maxspeed: list = field(default_factory=list)

    def __len__(self):
        return len(self.coords)

    def clip(self, bbox):
        """يبقي الخطوط التي يتقاطع امتدادها مع bbox (lon_min, lat_min, lon_max, lat_max): لقص ملفات الدول للمنطقة المدروسة."""
        w, s, e, n = bbox
        keep = [i for i, c in enumerate(self.coords) if c[:, 0].max() >= w and c[:, 0].min() <= e and c[:, 1].max() >= s and c[:, 1].min() <= n]
        pick = lambda lst: [lst[i] for i in keep] if lst else lst  # noqa: E731
        return Lines(pick(self.coords), pick(self.fclass), pick(self.oneway), pick(self.maxspeed))


def _oneway_code(v):
    """يوحّد صيغ الاتجاه الواحد: B (الاتجاهان) / F (مع الرسم) / T (عكسه)."""
    s = str(v).strip().lower() if v is not None else ""
    if s in ("f", "yes", "1", "true"):
        return "F"
    if s in ("t", "-1", "reverse"):
        return "T"
    return "B"


def _speed(v):
    if v is None:
        return np.nan
    m = re.search(r"\d+(\.\d+)?", str(v))
    if not m:
        return np.nan
    x = float(m.group())
    return x * 1.609 if "mph" in str(v).lower() else x


def from_geojson(obj):
    """GeoJSON (FeatureCollection خطوط). الحقول: fclass أو highway، oneway، maxspeed."""
    co, fc, ow, ms = [], [], [], []
    for f in obj.get("features", []):
        g = f.get("geometry") or {}
        props = f.get("properties") or {}
        parts = g.get("coordinates") if g.get("type") == "MultiLineString" else [g.get("coordinates")] if g.get("type") == "LineString" else []
        for part in parts:
            a = np.asarray(part, float)[:, :2]
            if len(a) >= 2:
                co.append(a)
                fc.append(str(props.get("fclass") or props.get("highway") or "road"))
                ow.append(_oneway_code(props.get("oneway")))
                ms.append(_speed(props.get("maxspeed")))
    return Lines(co, fc, ow, ms)


def from_overpass(obj):
    """استجابة Overpass JSON (out geom): عناصر way فيها geometry وtags.highway."""
    co, fc, ow, ms = [], [], [], []
    for el in obj.get("elements", []):
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        tags = el.get("tags", {})
        if "highway" not in tags:
            continue
        a = np.array([[p["lon"], p["lat"]] for p in el["geometry"]], float)
        if len(a) >= 2:
            co.append(a)
            fc.append(tags["highway"])
            ow.append(_oneway_code(tags.get("oneway") if tags.get("junction") != "roundabout" or "oneway" in tags else "yes"))
            ms.append(_speed(tags.get("maxspeed")))
    return Lines(co, fc, ow, ms)


def overpass_query(bbox, timeout=120):
    """استعلام Overpass للطرق ضمن (lon_min, lat_min, lon_max, lat_max). يستثني المشاة والدرجات."""
    w, s, e, n = bbox
    cls = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
    return f'[out:json][timeout:{timeout}];way["highway"~"^({cls})$"]({s},{w},{n},{e});out geom;'


def fetch_overpass(bbox, endpoint="https://overpass-api.de/api/interpreter", timeout=120):
    """تنزيل الطرق من Overpass (يحتاج اتصالاً بالإنترنت). المناطق الكبيرة تُحمَّل من ملف Geofabrik بدلاً من ذلك."""
    import urllib.parse
    import urllib.request

    req = urllib.request.Request(endpoint, data=urllib.parse.urlencode({"data": overpass_query(bbox, timeout)}).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout + 10) as r:  # noqa: S310
        return from_overpass(json.loads(r.read().decode("utf-8")))


def read_roads(data, filename="roads.geojson", bbox=None):
    """يقرأ ملف شوارع مرفوع: GeoJSON/JSON، أو zip (shapefile من Geofabrik)، أو GPKG. bbox اختياري (lon/lat) لقص الملفات الكبيرة."""
    name = filename.lower()
    if name.endswith((".geojson", ".json")):
        obj = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
        lines = from_overpass(obj) if "elements" in obj else from_geojson(obj)
    else:
        try:
            import tempfile

            import geopandas as gpd
        except ImportError as e:
            raise RoadDataError(
                'قراءة shapefile/GPKG تحتاج المكتبة geopandas: pip install "transport-hub[gis]"، أو ارفع الشوارع بصيغة GeoJSON'
            ) from e
        with tempfile.TemporaryDirectory() as td:
            p = f"{td}/{filename}"
            open(p, "wb").write(data if isinstance(data, (bytes, bytearray)) else data.read())
            src = f"zip://{p}" if name.endswith(".zip") else p
            gdf = gpd.read_file(src, bbox=bbox)
        gdf = gdf.to_crs(4326)
        col = "fclass" if "fclass" in gdf else "highway" if "highway" in gdf else None
        co, fc, ow, ms = [], [], [], []
        for i, g in enumerate(gdf.geometry):
            if g is None or g.is_empty:
                continue
            for part in g.geoms if hasattr(g, "geoms") else [g]:
                a = np.asarray(part.coords)[:, :2]
                if len(a) >= 2:
                    co.append(a)
                    fc.append(str(gdf[col].iat[i]) if col else "road")
                    ow.append(_oneway_code(gdf["oneway"].iat[i]) if "oneway" in gdf else "B")
                    ms.append(_speed(gdf["maxspeed"].iat[i]) if "maxspeed" in gdf else np.nan)
        lines = Lines(co, fc, ow, ms)
    if len(lines) == 0:
        raise RoadDataError("لا خطوط شوارع صالحة في الملف (تأكد أنه خطوط LineString وفيه fclass أو highway)")
    return lines


def _csr_min(n, u, v, w):
    """مصفوفة CSR تحتفظ بأقل وزن لكل زوج (u,v) (coo يجمع المكرر، ونحن نريد الأقل)."""
    df = pd.DataFrame({"u": u, "v": v, "w": np.maximum(w, 1e-6)}).groupby(["u", "v"], as_index=False)["w"].min()
    return csr_matrix((df["w"].to_numpy(), (df["u"].to_numpy(), df["v"].to_numpy())), shape=(n, n))


class RoadNetwork:
    """شبكة شوارع مسقطة: عقد وأضلاع، رسم قيادة موجّه (مسافة/زمن) ورسم مشي غير موجّه."""

    def __init__(self, lines, proj, peak_factor=PEAK_FACTOR):
        self.proj = proj
        sizes = np.array([len(c) for c in lines.coords])
        allc = np.concatenate(lines.coords)
        x, y = proj.xy(allc[:, 0], allc[:, 1])
        key = np.round(x / NODE_PRECISION).astype(np.int64) * 8_000_000_000 + np.round(y / NODE_PRECISION).astype(np.int64)
        uniq, inv = np.unique(key, return_inverse=True)
        n = len(uniq)
        nx_ = np.zeros(n)
        ny_ = np.zeros(n)
        nx_[inv] = x
        ny_[inv] = y
        self.node_xy = np.column_stack([nx_, ny_])
        line_id = np.repeat(np.arange(len(sizes)), sizes)
        same = line_id[:-1] == line_id[1:]
        a, b = inv[:-1][same], inv[1:][same]
        ln = line_id[:-1][same]
        keep = a != b
        a, b, ln = a[keep], b[keep], ln[keep]
        length = np.hypot(nx_[a] - nx_[b], ny_[a] - ny_[b])
        fc = np.array(lines.fclass, dtype=object)[ln]
        base = np.array([DRIVE_KMH.get(str(f).replace("_link", ""), 25) * (0.7 if str(f).endswith("_link") else 1.0) for f in fc], float)
        ms = np.array(lines.maxspeed if lines.maxspeed else [np.nan] * len(lines), float)[ln]
        kmh_free = np.where(np.isfinite(ms) & (ms > 5), ms, base)  # سرعة السير الحر (بدون ازدحام)
        kmh = kmh_free
        ow = np.array(lines.oneway if lines.oneway else ["B"] * len(lines), dtype=object)[ln]
        tsec = length / (kmh / 3.6)
        fwd, rev = ow != "T", ow != "F"
        du = np.concatenate([a[fwd], b[rev]])
        dv = np.concatenate([b[fwd], a[rev]])
        dl = np.concatenate([length[fwd], length[rev]])
        dt = np.concatenate([tsec[fwd], tsec[rev]])
        self.n_nodes, self.n_edges = n, len(du)
        self.peak_factor = peak_factor
        self.default_factor = 1.0 / peak_factor  # عامل الازدحام الافتراضي (يعادل سرعة الذروة القديمة)
        self._du, self._dv, self._dl, self._dt = du, dv, dl, dt  # أضلاع موجّهة وزمن السير الحر (ث)
        self._time_cache = {}
        self.oneway_share = float((ow != "B").mean())
        self._drive_len = _csr_min(n, du, dv, dl)
        self._drive_time = _csr_min(n, du, dv, dt * self.default_factor)
        wm = np.array([str(f) not in WALK_EXCLUDED for f in fc])
        wu, wv, wl = np.concatenate([a[wm], b[wm]]), np.concatenate([b[wm], a[wm]]), np.concatenate([length[wm], length[wm]])
        self._walk = _csr_min(n, wu, wv, wl)
        self.total_km = float(length.sum() / 1000)
        self._trees = {}
        self._comp = {}
        self._select_components()
        log.info("شبكة شوارع: %d عقدة، %d ضلع موجّه، %.0f كم، اتجاه واحد %.0f%%", n, self.n_edges, self.total_km, 100 * self.oneway_share)

    def _select_components(self):
        _, lab = connected_components(self._drive_len, directed=True, connection="strong")
        big = np.bincount(lab).argmax()
        self._comp["drive"] = np.where(lab == big)[0]
        _, labw = connected_components(self._walk, directed=False)
        self._comp["walk"] = np.where(labw == np.bincount(labw).argmax())[0]

    def _tree(self, mode):
        if mode not in self._trees:
            idx = self._comp[mode]
            self._trees[mode] = (idx, cKDTree(self.node_xy[idx]))
        return self._trees[mode]

    def snap(self, xy, mode="walk"):
        """أقرب عقدة في المكوّن الرئيسي: (العقدة، مسافة الربط م). المسافة > MAX_SNAP_M تعني «غير مرتبطة» (-1)."""
        idx, t = self._tree(mode)
        d, i = t.query(np.asarray(xy, float))
        node = idx[i]
        return np.where(d <= MAX_SNAP_M, node, -1), d

    @property
    def fingerprint(self):
        """بصمة الشبكة: لربط ملف الازدحام المتعلَّم بنفس الشبكة (تتغير بتغير الشوارع)."""
        return f"{self.n_nodes}:{self.n_edges}:{self.total_km:.2f}"

    def graph(self, mode, weight="length", profile=None, period=None):
        if mode == "walk":
            return self._walk
        if weight != "time":
            return self._drive_len
        if profile is None or period is None:
            return self._drive_time
        key = (profile.key, period)
        if key not in self._time_cache:
            self._time_cache[key] = _csr_min(self.n_nodes, self._du, self._dv, self._dt * profile.edge_factors(period, self))
        return self._time_cache[key]

    def edge_index(self):
        """مفتاح (u*n+v) → فهرس أسرع ضلع موجّه، لتحويل مسار العقد إلى أضلاع."""
        if not hasattr(self, "_eidx"):
            order = np.lexsort((self._dt, self._dv, self._du))
            k = self._du[order].astype(np.int64) * self.n_nodes + self._dv[order]
            first = np.concatenate([[True], k[1:] != k[:-1]])
            self._eidx = (k[first], order[first])
        return self._eidx

    def path_edges(self, a_xy, b_xy, profile=None, period=None):
        """أضلاع أقصر مسار قيادة (بالزمن) بين نقطتين: (فهارس الأضلاع، عقد المسار) أو (None, None)."""
        a_xy, b_xy = np.asarray(a_xy, float).reshape(-1, 2)[:1], np.asarray(b_xy, float).reshape(-1, 2)[:1]
        an, _ = self.snap(a_xy, "drive")
        bn, _ = self.snap(b_xy, "drive")
        if an[0] < 0 or bn[0] < 0:
            return None, None
        d, pred = dijkstra(self.graph("drive", "time", profile, period), directed=True, indices=int(an[0]), return_predecessors=True)
        if not np.isfinite(d[bn[0]]):
            return None, None
        path = [int(bn[0])]
        while path[-1] != an[0] and pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        path = np.array(path[::-1])
        if len(path) < 2:
            return np.array([], int), path
        keys, idx = self.edge_index()
        q = path[:-1].astype(np.int64) * self.n_nodes + path[1:]
        return idx[np.searchsorted(keys, q)], path

    # ───────── مشي ─────────
    def walk_within(self, src_xy, dst_xy, radius, batch=40):
        """لكل هدف (محطة/مرشح): مصادر ضمن مسافة مشي radius على الشبكة. يرجع (فهرس الهدف، فهرس المصدر، المسافة م) كمصفوفات.
        مسافة الربط (من النقطة لأقرب عقدة) تُضاف للنتيجة."""
        sn, sd = self.snap(src_xy, "walk")
        dn, dd = self.snap(dst_xy, "walk")
        ok_s = np.where(sn >= 0)[0]
        by_node = {}
        for i in ok_s:
            by_node.setdefault(sn[i], []).append(i)
        un = np.array(list(by_node))
        res_t, res_s, res_d = [], [], []
        g = self._walk
        ok_d = np.where(dn >= 0)[0]
        for k in range(0, len(ok_d), batch):
            bi = ok_d[k : k + batch]
            D = dijkstra(g, directed=False, indices=dn[bi], limit=float(radius))
            sub = D[:, un]
            for r, t in enumerate(bi):
                hit = np.where(sub[r] + dd[t] <= radius)[0]
                for h in hit:
                    for i in by_node[un[h]]:
                        total = sub[r, h] + dd[t] + sd[i]
                        if total <= radius:
                            res_t.append(t)
                            res_s.append(i)
                            res_d.append(total)
        return np.array(res_t, int), np.array(res_s, int), np.array(res_d, float)

    def walk_nearest(self, src_xy, dst_xy, limit=5000):
        """أقصر مسافة مشي من كل مصدر لأقرب هدف: (المسافة م، فهرس الهدف). inf إن لم تُبلغ ضمن limit أو كانت النقطة غير مرتبطة."""
        sn, sd = self.snap(src_xy, "walk")
        dn, dd = self.snap(dst_xy, "walk")
        ok = np.where(dn >= 0)[0]
        if len(ok) == 0:
            return np.full(len(sn), np.inf), np.full(len(sn), -1)
        D, _pred, srcs = dijkstra(self._walk, directed=False, indices=dn[ok], min_only=True, limit=float(limit), return_predecessors=True)
        out = np.full(len(sn), np.inf)
        idx = np.full(len(sn), -1)
        valid = sn >= 0
        node_d = D[sn[valid]]
        node_s = srcs[sn[valid]]
        node_to_dst = {}
        for j in ok:
            node_to_dst.setdefault(dn[j], j)
        tgt = np.array([node_to_dst.get(s_, -1) for s_ in node_s], dtype=int)
        legs = np.where(tgt >= 0, dd[np.maximum(tgt, 0)], 0)
        out[valid] = np.where(np.isfinite(node_d) & (tgt >= 0), node_d + sd[valid] + legs, np.inf)
        idx[valid] = tgt
        return out, idx

    # ───────── قيادة ─────────
    def drive_pairs(self, a_xy, b_xy, weight="length", limit=None, profile=None, period=None):
        """قيادة نقطة-لنقطة (أزواج مرتبة a[i]→b[i]) مع الاتجاه الواحد: يرجع (قيمة، لكل زوج؛ inf إن لم يُربط أو لم يوجد مسار)."""
        an, ad = self.snap(a_xy, "drive")
        bn, bd = self.snap(b_xy, "drive")
        g = self.graph("drive", weight, profile, period)
        out = np.full(len(an), np.inf)
        by_src = {}
        for i, (s, t) in enumerate(zip(an, bn)):
            if s >= 0 and t >= 0:
                by_src.setdefault(s, []).append(i)
        srcs = list(by_src)
        for k in range(0, len(srcs), 40):
            chunk = srcs[k : k + 40]
            D = dijkstra(g, directed=True, indices=chunk, limit=limit if limit else np.inf)
            for r, s in enumerate(chunk):
                for i in by_src[s]:
                    out[i] = D[r, bn[i]]
        if weight == "length":
            out = out + ad + bd
        else:
            out = out + (ad + bd) / (20 / 3.6)  # ربط بسرعة 20 كم/س
        return out

    def drive_matrix(self, src_xy, dst_xy, weight="length", batch=40, profile=None, period=None):
        """مصفوفة قيادة موجّهة src×dst (مسافة م أو زمن ث)."""
        sn, sd = self.snap(src_xy, "drive")
        dn, dd = self.snap(dst_xy, "drive")
        g = self.graph("drive", weight, profile, period)
        out = np.full((len(sn), len(dn)), np.inf)
        uniq = np.unique(sn[sn >= 0])
        rows = {}
        for k in range(0, len(uniq), batch):
            chunk = uniq[k : k + batch]
            D = dijkstra(g, directed=True, indices=chunk)
            for r, s in enumerate(chunk):
                rows[s] = D[r, np.maximum(dn, 0)]
        ok_d = dn >= 0
        k_leg = 1.0 if weight == "length" else 1 / (20 / 3.6)
        for i, s in enumerate(sn):
            if s >= 0:
                row = np.where(ok_d, rows[s] + (sd[i] + dd) * k_leg, np.inf)
                out[i] = row
        return out

    def drive_path(self, a_xy, b_xy, weight="time", profile=None, period=None):
        """خط المسار بين نقطتين على الشبكة (إحداثيات مسقطة) أو None."""
        a_xy, b_xy = np.asarray(a_xy, float).reshape(-1, 2)[:1], np.asarray(b_xy, float).reshape(-1, 2)[:1]
        an, _ = self.snap(a_xy, "drive")
        bn, _ = self.snap(b_xy, "drive")
        if an[0] < 0 or bn[0] < 0:
            return None
        d, pred = dijkstra(self.graph("drive", weight, profile, period), directed=True, indices=int(an[0]), return_predecessors=True)
        if not np.isfinite(d[bn[0]]):
            return None
        path = [int(bn[0])]
        while path[-1] != an[0] and pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        return self.node_xy[path[::-1]]

    def summary(self):
        return dict(
            nodes=self.n_nodes,
            directed_edges=self.n_edges,
            km=round(self.total_km, 1),
            oneway_pct=round(100 * self.oneway_share, 1),
            drive_nodes=len(self._comp["drive"]),
            walk_nodes=len(self._comp["walk"]),
        )
