"""خريطة HTML (Leaflet) بدون أي بيانات شخصية: المستوى والمدرسة والمرحلة والأسباب فقط."""
import json

import numpy as np

import config as C
from src.export_gis import lonlat

STAGES = ["ابتدائي", "متوسط", "ثانوي", "طفولة مبكرة", "غير معروف"]
LV = {"سهل": 0, "متوسط": 1, "صعب": 2}
REC = {"large": 0, "medium": 1, "small": 2, "pickup": 3}


def build(df, pickups, obst, schools, districts, streets, path):
    lon, lat = lonlat(df.x, df.y)
    sch_list = sorted(df["school"].unique())
    sidx = {s: i for i, s in enumerate(sch_list)}
    conf = {"عالية": 2, "متوسطة": 1, "منخفضة": 0}
    stu = [[round(float(lat[i]), 5), round(float(lon[i]), 5), LV[r.level_L], LV[r.level_M], LV[r.level_S],
            REC[r.rec_vehicle], sidx[r.school], STAGES.index(r.stage) if r.stage in STAGES else 4,
            conf.get(r.conf_L, 1), r.reasons_L]
           for i, r in enumerate(df.itertuples())]
    pk = []
    if pickups is not None and len(pickups):
        plon, plat = lonlat(pickups.x, pickups.y)
        pk = [[round(float(plat[i]), 5), round(float(plon[i]), 5), int(r.students), int(r.max_walk)]
              for i, r in enumerate(pickups.itertuples())]
    ob = []
    if obst is not None and len(obst):
        o = obst[obst["veh"] == "large"]
        olon, olat = lonlat(o.x, o.y)
        ob = [[round(float(olat[i]), 5), round(float(olon[i]), 5), r.type, int(r.reverse_m)] for i, r in enumerate(o.itertuples())]
    slon, slat = lonlat(schools.x, schools.y)
    sc = [[round(float(slat[i]), 5), round(float(slon[i]), 5), n] for i, n in enumerate(schools["name"])]
    dist = []
    for g in districts.geometry:
        for poly in (g.geoms if hasattr(g, "geoms") else [g]):
            x, y = lonlat(*np.array(poly.simplify(100).exterior.coords).T)
            dist.append([[round(float(b), 5), round(float(a), 5)] for a, b in zip(x, y)])
    major = []
    if streets is not None and len(streets):
        for c in streets.loc[streets["is_major"], "coords"]:
            x, y = lonlat(c[:, 0], c[:, 1])
            major.append([[round(float(b), 5), round(float(a), 5)] for a, b in zip(x[::3], y[::3])])
    data = dict(students=stu, schools_list=sch_list, stages=STAGES, pickups=pk, obstacles=ob, schools=sc,
                districts=dist, major=major)
    tpl = (C.PROJECT / "templates" / "webmap_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    open(path, "w", encoding="utf-8").write(html)
