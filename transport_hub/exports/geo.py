"""تصدير الجداول المكانية: GeoJSON وKML وCSV (UTF-8 مع BOM لفتح العربي في Excel)."""

import html
import json

import numpy as np
import pandas as pd


def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if (np.isnan(v) or np.isinf(v)) else round(float(v), 4)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if v is None or isinstance(v, (int, str, bool)):
        return v
    return str(v)


def _props(df, skip):
    cols = [c for c in df.columns if c not in skip and df[c].map(lambda x: not isinstance(x, (list, dict, np.ndarray))).all()]
    return cols


def to_geojson(df, lon="lon", lat="lat", skip=("x", "y", "px", "py", "dx", "dy")):
    """FeatureCollection نقاط (WGS84)، الخصائص كل الأعمدة البسيطة."""
    d = df.dropna(subset=[lon, lat])
    cols = _props(d, set(skip) | {lon, lat})
    feats = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(float(r[lon]), 6), round(float(r[lat]), 6)]},
            "properties": {c: _clean(r[c]) for c in cols},
        }
        for r in d.to_dict("records")
    ]
    return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).encode("utf-8")


def to_kml(df, name_col=None, lon="lon", lat="lat", doc_name="نقاط", skip=("x", "y", "px", "py", "dx", "dy")):
    d = df.dropna(subset=[lon, lat])
    cols = _props(d, set(skip) | {lon, lat})
    out = ['<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>{html.escape(doc_name)}</name>"]
    for i, r in enumerate(d.to_dict("records"), 1):
        nm = str(r[name_col]) if name_col and name_col in r else f"{i}"
        desc = "<br/>".join(f"{html.escape(str(c))}: {html.escape(str(_clean(r[c])))}" for c in cols)
        out.append(
            f"<Placemark><name>{html.escape(nm)}</name><description><![CDATA[{desc}]]></description>"
            f"<Point><coordinates>{float(r[lon]):.6f},{float(r[lat]):.6f},0</coordinates></Point></Placemark>"
        )
    out.append("</Document></kml>")
    return "".join(out).encode("utf-8")


def to_csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


LINE_COLS = {"lon_a", "lat_a", "lon_b", "lat_b"}


def is_lines(df):
    return LINE_COLS <= set(df.columns)


def to_geojson_lines(df, skip=()):
    """FeatureCollection خطوط (قطعة من lon_a,lat_a إلى lon_b,lat_b) والخصائص بقية الأعمدة البسيطة."""
    d = df.dropna(subset=list(LINE_COLS))
    cols = _props(d, set(skip) | LINE_COLS)
    feats = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [round(float(r["lon_a"]), 6), round(float(r["lat_a"]), 6)],
                    [round(float(r["lon_b"]), 6), round(float(r["lat_b"]), 6)],
                ],
            },
            "properties": {c: _clean(r[c]) for c in cols},
        }
        for r in d.to_dict("records")
    ]
    return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).encode("utf-8")


def to_kml_lines(df, doc_name="خطوط"):
    d = df.dropna(subset=list(LINE_COLS))
    cols = _props(d, LINE_COLS)
    out = ['<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>{html.escape(doc_name)}</name>"]
    for i, r in enumerate(d.to_dict("records"), 1):
        desc = "<br/>".join(f"{html.escape(str(c))}: {html.escape(str(_clean(r[c])))}" for c in cols)
        out.append(
            f"<Placemark><name>{i}</name><description><![CDATA[{desc}]]></description><LineString><coordinates>"
            f"{float(r['lon_a']):.6f},{float(r['lat_a']):.6f},0 {float(r['lon_b']):.6f},{float(r['lat_b']):.6f},0</coordinates></LineString></Placemark>"
        )
    out.append("</Document></kml>")
    return "".join(out).encode("utf-8")
