"""أدوات جغرافية مشتركة: إسقاط تلقائي (UTM)، مسافات، شبكات خلايا، وأقرب نقطة."""

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

DETOUR = 1.3  # معامل التعرج: المسافة الفعلية على الشوارع ≈ 1.3 × الخط المستقيم (تقديري)
WALK_KMH = 4.8  # سرعة المشي


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


class Projector:
    """إسقاط UTM يُختار من مركز البيانات (أو يُحدد يدوياً)."""

    def __init__(self, epsg):
        self.epsg = int(epsg)
        self._fwd = Transformer.from_crs(4326, self.epsg, always_xy=True)
        self._inv = Transformer.from_crs(self.epsg, 4326, always_xy=True)

    @classmethod
    def for_points(cls, lon, lat):
        return cls(utm_epsg(float(np.mean(lon)), float(np.mean(lat))))

    def xy(self, lon, lat):
        x, y = self._fwd.transform(np.asarray(lon, float), np.asarray(lat, float))
        return np.asarray(x), np.asarray(y)

    def lonlat(self, x, y):
        lo, la = self._inv.transform(np.asarray(x, float), np.asarray(y, float))
        return np.asarray(lo), np.asarray(la)

    def attach(self, df, lon="lon", lat="lat"):
        df = df.copy()
        df["x"], df["y"] = self.xy(df[lon].values, df[lat].values)
        return df

    def attach_lonlat(self, df):
        df = df.copy()
        df["lon"], df["lat"] = self.lonlat(df["x"].values, df["y"].values)
        return df


def haversine_m(lon1, lat1, lon2, lat2):
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def nearest(src_xy, dst_xy):
    """أقرب نقطة من dst لكل نقطة في src → (المسافة، الفهرس)."""
    if len(dst_xy) == 0:
        return np.full(len(src_xy), np.inf), np.full(len(src_xy), -1)
    return cKDTree(dst_xy).query(np.asarray(src_xy, float))


def grid_cells(x, y, cell):
    """رقم الخلية لكل نقطة (ix, iy) ومركزها."""
    ix = np.floor(np.asarray(x) / cell).astype(int)
    iy = np.floor(np.asarray(y) / cell).astype(int)
    return ix, iy, (ix + 0.5) * cell, (iy + 0.5) * cell


def candidate_grid(x, y, cell, margin=0.0):
    """خلايا مرشحة تغطي امتداد النقاط (مراكز الخلايا)."""
    x0, x1 = np.min(x) - margin, np.max(x) + margin
    y0, y1 = np.min(y) - margin, np.max(y) + margin
    xs = np.arange(np.floor(x0 / cell) * cell + cell / 2, x1 + cell, cell)
    ys = np.arange(np.floor(y0 / cell) * cell + cell / 2, y1 + cell, cell)
    gx, gy = np.meshgrid(xs, ys)
    return pd.DataFrame({"x": gx.ravel(), "y": gy.ravel()})


def walk_minutes(dist_m):
    """زمن المشي (د) لمسافة مستقيمة بعد معامل التعرج."""
    return np.asarray(dist_m) * DETOUR / (WALK_KMH * 1000 / 60)
