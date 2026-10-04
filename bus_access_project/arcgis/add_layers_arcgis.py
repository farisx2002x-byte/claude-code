# -*- coding: utf-8 -*-
"""يضيف طبقات التحليل لخريطة ArcGIS Pro الحالية بألوانها (UniqueValueRenderer).
الاستخدام داخل Python Window في ArcGIS Pro:
    exec(open(r"<مسار المشروع>\\arcgis\\add_layers_arcgis.py", encoding="utf-8").read())
    add_layers()
"""
import os

import arcpy

LEVEL_COL = {"سهل": [46, 158, 79, 100], "متوسط": [224, 168, 0, 100], "صعب": [209, 56, 61, 100]}
VEH_COL = {"باص كبير": [21, 101, 192, 100], "باص متوسط": [239, 108, 0, 100], "فان": [106, 27, 154, 100],
           "نقطة تجميع / ترتيب خاص": [120, 120, 120, 100]}
WCODE_COL = {1: [209, 56, 61, 100], 2: [239, 108, 0, 100], 3: [224, 168, 0, 100], 4: [139, 195, 74, 100], 5: [46, 158, 79, 100]}
VCODE_COL = {1: [21, 101, 192, 100], 2: [239, 108, 0, 100], 3: [106, 27, 154, 100], 4: [158, 158, 158, 100]}
OBST_COL = {"turn_sharp": [255, 213, 79, 100], "turn_vsharp": [255, 112, 67, 100], "deadend": [213, 0, 0, 100]}

DEFAULT_GPKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "تحليل_وصول_الباص.gpkg")


def _unique(layer, field, colors, size=None, line_width=None):
    sym = layer.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = [field]
    for item in sym.renderer.groups[0].items:
        key = item.values[0][0]
        for k, col in colors.items():
            if str(k) == str(key):
                item.symbol.color = {"RGB": col}
                if size:
                    item.symbol.size = size
                if line_width:
                    item.symbol.width = line_width
    layer.symbology = sym


def add_layers(gpkg=None, m=None):
    gpkg = gpkg or DEFAULT_GPKG
    if m is None:
        m = arcpy.mp.ArcGISProject("CURRENT").activeMap
    spec = [
        ("streets_bus_width", "الشوارع حسب العرض", "wcode", WCODE_COL, dict(line_width=1.5)),
        ("streets_bus_width", "الشوارع حسب المركبة", "vcode", VCODE_COL, dict(line_width=1.5)),
        ("bus_obstacles", "العوائق", "type", OBST_COL, dict(size=6)),
        ("bus_routes", "المسارات", None, None, {}),
        ("route_stops", "وقفات المسارات", None, None, {}),
        ("students_access", "الطلاب حسب المستوى", "level", LEVEL_COL, dict(size=4)),
        ("students_access", "الطلاب حسب المركبة الموصى بها", "rec_vehicle", VEH_COL, dict(size=4)),
        ("pickup_points", "نقاط التجميع", None, None, {}),
        ("schools", "المدارس", None, None, {}),
    ]
    added = []
    for fc, title, field, colors, kw in spec:
        path = os.path.join(gpkg, "main." + fc)
        if not arcpy.Exists(path):
            continue
        lyr = m.addDataFromPath(path)
        lyr.name = title
        if field:
            try:
                _unique(lyr, field, colors, **kw)
            except Exception as e:  # التلوين اختياري، لا نوقف إضافة الطبقات
                arcpy.AddWarning(f"تعذر تلوين {title}: {e}")
        added.append(title)
    arcpy.AddMessage("أضيفت الطبقات: " + "، ".join(added))
    return added
