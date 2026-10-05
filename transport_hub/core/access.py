"""واجهة موحّدة لمسافات الوصول: شبكة شوارع OSM إن توفرت، وإلا تقدير مستقيم × معامل التعرج. كل الوحدات تتعامل معها بنفس الكود."""

import numpy as np
from scipy.spatial import cKDTree

from transport_hub.core import geo

EST_FREE_KMH = 37.5  # سرعة السير الحر المقدّرة بدون شبكة؛ × عامل الازدحام الافتراضي 1.25 = 30 كم/س
EST_DEFAULT_FACTOR = 1.25
EST_DRIVE_KMH = EST_FREE_KMH / EST_DEFAULT_FACTOR


class Access:
    """net: RoadNetwork أو None. النقاط غير المرتبطة بالشبكة (> 300 م عن أقرب شارع) تُقدَّر بالخط المستقيم × المعامل ويُحصى عددها."""

    def __init__(self, net=None, detour=geo.DETOUR, profile=None, period=None):
        self.net = net
        self.detour = detour
        self.unlinked = 0
        self.profile = profile  # عوامل الازدحام (Profile) أو None
        self.period = period  # فترة اليوم لحساب أزمنة القيادة (None = الافتراضي)

    def congestion_label(self):
        if self.profile is None:
            return "غير مطبّق (الأزمنة بسرعات الفئة × 0.8 للذروة)"
        from transport_hub.core.congestion import PERIOD_KEYS

        return f"{self.profile.source}: " + "، ".join(f"{p} ×{self.profile.factor(p):.2f}" for p in PERIOD_KEYS)

    def with_period(self, period):
        """نسخة خفيفة بنفس الشبكة والازدحام لكن بفترة يوم محددة: أزمنة القيادة تتبع ازدحام تلك الفترة."""
        return Access(self.net, self.detour, self.profile, period)

    def _est_factor(self):
        return self.profile.factor(self.period) if (self.profile is not None and self.period is not None) else EST_DEFAULT_FACTOR

    def _est_time(self, dist_m):
        return dist_m / (EST_FREE_KMH / 3.6) * self._est_factor()

    @property
    def mode(self):
        return "osm" if self.net is not None else "estimate"

    def label(self):
        if self.net is None:
            return f"تقدير: خط مستقيم × {self.detour:g}"
        s = self.net.summary()
        return f"شبكة شوارع OSM ({s['km']:,.0f} كم، {s['oneway_pct']:.0f}% اتجاه واحد)"

    # ───────── مشي ─────────
    def _est_cover(self, src_xy, dst_xy, radius):
        src_xy, dst_xy = np.asarray(src_xy, float), np.asarray(dst_xy, float)
        if len(src_xy) == 0 or len(dst_xy) == 0:
            return np.array([], int), np.array([], int), np.array([], float)
        tree = cKDTree(src_xy)
        t, s, d = [], [], []
        for j, lst in enumerate(tree.query_ball_point(dst_xy, radius / self.detour)):
            if lst:
                dist = np.hypot(src_xy[lst, 0] - dst_xy[j, 0], src_xy[lst, 1] - dst_xy[j, 1]) * self.detour
                t.extend([j] * len(lst))
                s.extend(lst)
                d.extend(dist)
        return np.array(t, int), np.array(s, int), np.array(d, float)

    def cover(self, src_xy, dst_xy, radius):
        """أزواج (هدف، مصدر، مسافة مشي) ضمن radius م. بالشبكة: مسافة الشارع الفعلية."""
        if self.net is None:
            return self._est_cover(src_xy, dst_xy, radius)
        t, s, d = self.net.walk_within(src_xy, dst_xy, radius)
        sn, _ = self.net.snap(src_xy, "walk")
        dn, _ = self.net.snap(dst_xy, "walk")
        bad_s, bad_d = sn < 0, dn < 0
        self.unlinked = int(bad_s.sum())
        if bad_s.any() or bad_d.any():  # غير المرتبط: تقدير للأزواج التي يدخل فيها
            et, es, ed = self._est_cover(src_xy, dst_xy, radius)
            m = bad_s[es] | bad_d[et]
            t, s, d = np.concatenate([t, et[m]]), np.concatenate([s, es[m]]), np.concatenate([d, ed[m]])
        return t, s, d

    def cover_lists(self, dst_xy, src_xy, radius):
        """لكل هدف: فهارس المصادر ضمن المسافة (للتغطية القصوى)."""
        t, s, _ = self.cover(src_xy, dst_xy, radius)
        out = [[] for _ in range(len(dst_xy))]
        for ti, si in zip(t, s):
            out[ti].append(int(si))
        return [np.array(x, int) for x in out]

    def walk_nearest(self, src_xy, dst_xy, limit=5000):
        """أقرب هدف لكل مصدر: (مسافة المشي م، فهرس الهدف)."""
        src_xy, dst_xy = np.asarray(src_xy, float), np.asarray(dst_xy, float)
        if len(dst_xy) == 0:
            return np.full(len(src_xy), np.inf), np.full(len(src_xy), -1)
        d_est, i_est = cKDTree(dst_xy).query(src_xy)
        d_est = d_est * self.detour
        if self.net is None:
            return d_est, i_est
        d, i = self.net.walk_nearest(src_xy, dst_xy, limit)
        bad = ~np.isfinite(d) & (self.net.snap(src_xy, "walk")[0] < 0)
        self.unlinked = int(bad.sum())
        d = np.where(bad, d_est, d)
        i = np.where(bad, i_est, i)
        return d, i

    # ───────── قيادة ─────────
    def drive_pairs(self, a_xy, b_xy, weight="length"):
        """أزواج مرتبة a[i]→b[i]: مسافة (م) أو زمن (ث)."""
        a_xy, b_xy = np.asarray(a_xy, float), np.asarray(b_xy, float)
        est = np.hypot(a_xy[:, 0] - b_xy[:, 0], a_xy[:, 1] - b_xy[:, 1]) * self.detour
        est = est if weight == "length" else self._est_time(est)
        if self.net is None:
            return est
        d = self.net.drive_pairs(a_xy, b_xy, weight, profile=self.profile, period=self.period)
        return np.where(np.isfinite(d), d, est)  # لا مسار موجّه (أو غير مرتبط): نرجع للتقدير بدل inf

    def drive_matrix(self, src_xy, dst_xy, weight="length"):
        src_xy, dst_xy = np.asarray(src_xy, float), np.asarray(dst_xy, float)
        est = np.hypot(src_xy[:, None, 0] - dst_xy[None, :, 0], src_xy[:, None, 1] - dst_xy[None, :, 1]) * self.detour
        est = est if weight == "length" else self._est_time(est)
        if self.net is None:
            return est
        d = self.net.drive_matrix(src_xy, dst_xy, weight, profile=self.profile, period=self.period)
        return np.where(np.isfinite(d), d, est)

    def drive_path(self, a_xy, b_xy, weight="time"):
        if self.net is not None:
            p = self.net.drive_path(a_xy, b_xy, weight, profile=self.profile, period=self.period)
            if p is not None:
                return p
        return np.array([a_xy, b_xy], float)


_NET_CACHE = {}


def load_access(ws, use=True, use_congestion=True, period=None):
    """Access من مساحة العمل: شبكة الشوارع إن وُجدت وuse=True (تُبنى مرة وتُخزَّن بالكاش حتى تتغير البيانات)، وإلا التقدير.
    ملف الازدحام ("congestion") يُطبَّق إن وُجد وتوافق مع الشبكة؛ ويؤثر على أزمنة القيادة فقط."""
    from transport_hub.core.roadnet import RoadNetwork

    profile = ws.obj("congestion") if use_congestion else None
    lines, epsg = ws.obj("roads_lines"), ws.obj("proj_epsg")
    if not use or lines is None or epsg is None:
        return Access(profile=profile if (profile is not None and profile.edge_factor is None) else None, period=period)
    key = (str(ws.root), ws.meta().get("roads_lines"), epsg)
    if key not in _NET_CACHE:
        _NET_CACHE.clear()
        _NET_CACHE[key] = RoadNetwork(lines, geo.Projector(epsg))
    net = _NET_CACHE[key]
    if profile is not None and not profile.compatible(net):
        profile = None  # تعلّم من شبكة مختلفة: لا يُطبَّق
    return Access(net, profile=profile, period=period)
