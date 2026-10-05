"""حزمة المخرجات: zip فيه Excel + تقرير HTML + ملفات GIS/CSV + manifest.json + README عربي، بنفس البصمة والمعاملات."""

import io
import json
import zipfile

from transport_hub.exports import excel, geo, html_report

README = """حزمة مخرجات منصة النقل
الإصدار: {version}   التاريخ: {generated}   البصمة: {fingerprint}

الملفات:
{files}

كل ملف مبني من نفس البيانات والمعاملات المذكورة في manifest.json (البصمة تتطابق).
{demo}
"""


def build_zip(meta, sheets, sections, geo_tables=None):
    """sheets: قائمة excel.Sheet. sections: أقسام التقرير. geo_tables: dict اسم → DataFrame فيه lon/lat (يُصدَّر GeoJSON وKML وCSV)."""
    buf = io.BytesIO()
    files = {}
    xl = io.BytesIO()
    excel.build_workbook(xl, sheets, meta)
    files["التقرير.xlsx"] = xl.getvalue()
    files["التقرير_التنفيذي.html"] = html_report.build(meta, sections).encode("utf-8")
    for name, df in (geo_tables or {}).items():
        if geo.is_lines(df):
            files[f"gis/{name}.geojson"] = geo.to_geojson_lines(df)
            files[f"gis/{name}.kml"] = geo.to_kml_lines(df, doc_name=name)
        else:
            files[f"gis/{name}.geojson"] = geo.to_geojson(df)
            files[f"gis/{name}.kml"] = geo.to_kml(df, doc_name=name)
        files[f"csv/{name}.csv"] = geo.to_csv(df)
    manifest = dict(meta, files=sorted(files), rows={s.name: len(s.df) for s in sheets})
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    listing = "\n".join(f" - {n}" for n in sorted(files))
    files["README.txt"] = README.format(
        files=listing,
        demo="⚠ مبني على بيانات تجريبية اصطناعية." if meta.get("demo") else "",
        **{k: meta[k] for k in ("version", "generated", "fingerprint")},
    ).encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()
