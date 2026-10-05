"""أدوات مشتركة للاختبارات: إسقاط ثابت، وبناء خطوط شوارع من إحداثيات بالمتر."""

import numpy as np

from transport_hub.core import geo
from transport_hub.core.roadnet import Lines

PROJ = geo.Projector(32637)
X0, Y0 = 520000.0, 2384000.0


def lines_xy(segs, fclass="residential", oneway="B"):
    """خطوط من إحداثيات مسقطة بالمتر (نسبة لنقطة أصل) → Lines بـ lon/lat."""
    co = []
    for s in segs:
        a = np.asarray(s, float)
        lo, la = PROJ.lonlat(X0 + a[:, 0], Y0 + a[:, 1])
        co.append(np.column_stack([lo, la]))
    n = len(co)
    return Lines(co, [fclass] * n, [oneway] * n if isinstance(oneway, str) else list(oneway), [np.nan] * n)


def grid(n=5, step=100.0, **kw):
    segs = []
    for i in range(n):
        segs.append([(i * step, j * step) for j in range(n)])
        segs.append([(j * step, i * step) for j in range(n)])
    return lines_xy(segs, **kw)


def pt(x, y):
    return np.array([[X0 + x, Y0 + y]])
