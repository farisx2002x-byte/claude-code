"""GeoPackage + KML الطلاب (داخلية، فيها أسماء) + نقاط التجميع + طبقة المدارس."""
import html

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point

import config as C

_to_ll = Transformer.from_crs(C.CRS_UTM, "EPSG:4326", always_xy=True)


def lonlat(x, y):
    return _to_ll.transform(np.asarray(x, float), np.asarray(y, float))


def _gdf(df, xcol="x", ycol="y"):
    return gpd.GeoDataFrame(df.drop(columns=[xcol, ycol], errors="ignore"),
                            geometry=gpd.points_from_xy(df[xcol], df[ycol]), crs=C.CRS_UTM)


def students_layer(df):
    """أسماء الحقول لا تفرق بين الكبير والصغير في GPKG، فنستخدم level_med وwalk_med_m وغيرها."""
    d = pd.DataFrame({
        "student_name": df["name"], "student_id": df["sid"], "school": df["school"], "stage": df["stage"],
        "district": df["district"], "zone": df["zone"],
        "level": df["level_L"], "score": df["score_L"], "walk_m": df["walk_used_L"], "confidence": df["conf_L"],
        "reasons": df["reasons_L"], "level_med": df["level_M"], "walk_med_m": df["walk_used_M"],
        "level_van": df["level_S"], "walk_van_m": df["walk_used_S"],
        "rec_vehicle": df["rec_vehicle_ar"], "pickup_id": df["pickup_id"], "route_id": df.get("route", np.nan),
        "x": df["x"], "y": df["y"]})
    return _gdf(d)


def streets_layer(streets):
    geom = [LineString(c) if len(c) > 1 else None for c in streets["coords"]]
    g = gpd.GeoDataFrame({
        "row_min_m": streets["p10"].round(1), "row_typ_m": streets["med"].round(1),
        "wcode": pd.cut(streets["p10"], [-1, 8, 10, 13, 16, 1e9], labels=[1, 2, 3, 4, 5]).astype(int),
        "reach_M": streets["reach_M"], "reach_S": streets["reach_S"],
        "vcode": np.where(streets["reach_L"], 1, np.where(streets["reach_M"], 2, np.where(streets["reach_S"], 3, 4))),
        "major": streets["is_major"], "tile": streets["tile"]}, geometry=geom, crs=C.CRS_UTM)
    return g[g.geometry.notna()]


def obstacles_layers(obst):
    if obst is None or obst.empty:
        e = gpd.GeoDataFrame({"type": [], "veh": [], "reverse_m": []}, geometry=[], crs=C.CRS_UTM)
        return e, e
    allv = _gdf(obst)
    return allv[allv["veh"] == "large"].copy(), allv


def write_gpkg(path, df, streets, obst, pickups, schools, routes_gdf=None, stops_gdf=None):
    path = str(path)
    first = [True]

    def put(g, layer):
        if g is None or len(g) == 0:
            return
        g.to_file(path, layer=layer, driver="GPKG", mode="w" if first[0] else "a")
        first[0] = False
    put(students_layer(df), "students_access")
    put(streets_layer(streets), "streets_bus_width")
    large, allv = obstacles_layers(obst)
    put(large, "bus_obstacles")
    put(allv, "obstacles_all_vehicles")
    if pickups is not None and len(pickups):
        put(_gdf(pickups), "pickup_points")
    put(_gdf(schools[["name", "x", "y"]]), "schools")
    put(routes_gdf, "bus_routes")
    put(stops_gdf, "route_stops")


def _kml_pt(name, desc, lon, lat):
    return (f"<Placemark><name>{html.escape(str(name))}</name><description><![CDATA[{desc}]]></description>"
            f"<Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point></Placemark>")


def write_students_kml(path, df, pickups, obst):
    """KML داخلي (فيه أسماء الطلاب): مجلدات حسب المستوى + نقاط التجميع + العوائق."""
    lon, lat = lonlat(df.x, df.y)
    out = ['<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           "<name>وصول الباص للطلاب (داخلي)</name>"]
    for lv in ("سهل", "متوسط", "صعب"):
        out.append(f"<Folder><name>{lv}</name>")
        for i in np.where(df["level_L"].values == lv)[0]:
            r = df.iloc[i]
            d = f"{r['school']} | {r['stage']} | {r['rec_vehicle_ar']}<br/>{html.escape(str(r['reasons_L']))}"
            out.append(_kml_pt(r["name"], d, lon[i], lat[i]))
        out.append("</Folder>")
    out.append("<Folder><name>نقاط التجميع</name>")
    if pickups is not None and len(pickups):
        plon, plat = lonlat(pickups.x, pickups.y)
        for k, r in enumerate(pickups.itertuples()):
            out.append(_kml_pt(f"نقطة تجميع {r.pickup_id}", f"{r.students} طالب، أبعد مشي {r.max_walk:.0f} م", plon[k], plat[k]))
    out.append("</Folder><Folder><name>العوائق</name>")
    if obst is not None and len(obst):
        o = obst[obst["veh"] == "large"]
        olon, olat = lonlat(o.x, o.y)
        names = {"turn_sharp": "التفاف حاد", "turn_vsharp": "التفاف حاد جداً", "deadend": "شارع مسدود"}
        for k, r in enumerate(o.itertuples()):
            out.append(_kml_pt(names.get(r.type, r.type), f"رجوع للخلف {r.reverse_m:.0f} م" if r.reverse_m else "", olon[k], olat[k]))
    out.append("</Folder></Document></kml>")
    open(path, "w", encoding="utf-8").write("".join(out))
