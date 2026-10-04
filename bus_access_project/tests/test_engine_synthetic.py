"""حي اصطناعي: بلوكات 60 م، شوارع 14 م، وزقاق مسدود 6 م. الكبير ما يدخل الزقاق والفان يدخله ويرجع للخلف."""
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, box

import config as C
from src import tile_engine as TE


def make_district():
    """شارع رئيسي عريض (26 م) على الحافة الجنوبية، وشبكة بلوكات 60 م وشوارع 14 م، وزقاق 6 م مسدود."""
    polys = []
    x = 0
    xs = []
    while x < 600:
        xs.append(x)
        x += 74
    ys = []
    y = 40
    while y < 400:
        ys.append(y)
        y += 74
    for x in xs:
        for y in ys:
            if x == 74 * 3 and y == ys[2]:   # بلوك مقسوم بزقاق مسدود عرضه 6 م
                polys.append(box(x, y, x + 27, y + 60))
                polys.append(box(x + 33, y, x + 60, y + 60))
                polys.append(box(x + 27, y + 54, x + 33, y + 60))   # سدّ الطرف الشمالي
                continue
            polys.append(box(x, y, x + 60, y + 60))
    # شارع رئيسي: الفراغ بين y=0 و y=40 أصلاً 40 م؛ نخليه 26 م بقطع شريط
    polys.append(box(-100, 0, 1000, 7))
    polys.append(box(-100, 33, 1000, 40))
    g = gpd.GeoDataFrame({"LU_ZONE": ["سكني"] * len(polys)}, geometry=polys, crs=C.CRS_UTM)
    return g


def run(vk, pts):
    polys = make_district()
    roads = gpd.GeoDataFrame({"fclass": []}, geometry=[], crs=C.CRS_UTM)
    core = (-50.0, -50.0, 700.0, 450.0)
    S = TE.build_streets(polys, roads, core)
    return S, TE.analyze_vehicle(S, vk, np.array(pts, float))


def test_streets_measured():
    S, _ = run("large", [(100, 100)])
    assert S.n_seg > 10
    # أغلب المقاطع عرضها ~14 م (الشوارع بين البلوكات)
    inner = S.p10[(S.p10 > 10) & (S.p10 < 20)]
    assert len(inner) > 5
    assert abs(np.median(inner) - 14) < 2


def test_large_reaches_street_front():
    # بيت بجانب شارع 14 م (الوسط بين بلوكين)
    S, (res, obs, reach) = run("large", [(67, 100)])
    assert res["access"][0]
    assert res["direct"][0]


def test_large_cannot_enter_alley_van_can():
    # الزقاق: x من 74*3+27 = 249 لين 255، وy عبر البلوك
    y = 40 + 74 * 2 + 20
    pt = (252.0, y)
    S, (rl, ol, _) = run("large", [pt])
    _, (rs, os_, _) = run("small", [pt])
    # الكبير ما يوصل الزقاق مباشرة (عرضه 6 < 8): إما مشي أو ما فيه وصول
    assert (not rl["direct"][0]) or rl["bottleneck_row"][0] < 8
    assert rs["access"][0]
    assert rs["direct"][0]
    assert rs["reverse_m"][0] > 0   # الفان يدخل ويرجع للخلف (الزقاق مسدود وصغير)


def test_walk_for_large_in_alley():
    y = 40 + 74 * 2 + 20
    _, (rl, _, _) = run("large", [(252.0, y)])
    if rl["access"][0] and not rl["direct"][0]:
        assert rl["walk_net_m"][0] > 0
