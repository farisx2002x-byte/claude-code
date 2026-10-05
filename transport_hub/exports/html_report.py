"""تقرير HTML تنفيذي مستقل (ملف واحد، RTL، جاهز للطباعة كـ PDF): مؤشرات، جداول، رسوم SVG، وخرائط نقطية مبسطة."""

import html
import math
import re

import numpy as np

from transport_hub.exports import dictionary as DICT

CSS = """
:root{--bg:#fff;--fg:#1b1f23;--mut:#667;--bd:#d8dee4;--card:#f6f8fa;--pri:#1f3864;--ok:#2e9e4f;--mid:#e0a800;--bad:#d1383d}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e6e8eb;--mut:#9aa4af;--bd:#2f3740;--card:#1b2026}}
@media print{:root{--bg:#fff;--fg:#000;--card:#fff}body{max-width:none;margin:0}.pb{page-break-before:always}a{color:inherit}}
*{box-sizing:border-box}body{font-family:Arial,Tahoma,sans-serif;background:var(--bg);color:var(--fg);max-width:980px;margin:0 auto;padding:24px 16px;line-height:1.6}
h1{font-size:1.9rem;margin:0 0 4px}h2{font-size:1.25rem;border-bottom:2px solid var(--pri);padding-bottom:4px;margin-top:32px}
.sub{color:var(--mut);margin:0 0 16px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px}.kpi b{display:block;font-size:1.5rem}.kpi span{color:var(--mut);font-size:.85rem}
.kpi.ok{border-right:4px solid var(--ok)}.kpi.mid{border-right:4px solid var(--mid)}.kpi.bad{border-right:4px solid var(--bad)}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:.9rem}th{background:var(--pri);color:#fff;padding:6px 8px;text-align:right}
td{padding:5px 8px;border-bottom:1px solid var(--bd)}tr:nth-child(even) td{background:var(--card)}
.note{color:var(--mut);font-size:.85rem}.warn{background:#fff4e5;color:#7a4a00;border:1px solid #f0c27a;border-radius:8px;padding:8px 12px;margin:10px 0}
.meta{font-size:.8rem;color:var(--mut);border-top:1px solid var(--bd);margin-top:40px;padding-top:10px}svg text{font-family:Arial,Tahoma,sans-serif}
"""
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


def nice_max(v, ticks=4):
    """سقف محور «لطيف» (1/2/2.5/5 × 10^k)، فتكون القيم على المحور أرقاماً مقروءة."""
    if v <= 0:
        return 1.0
    raw = v / ticks
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw) * ticks


def _tick(v, fmt):
    return fmt.format(v) if float(v).is_integer() else f"{v:,.1f}"


def bar_svg(labels, values, title="", width=620, height=240, color="#1f77b4", fmt="{:,.0f}"):
    """رسم أعمدة SVG بسيط بتسميات وقيم فوق الأعمدة."""
    n = len(values)
    if n == 0:
        return ""
    vmax = nice_max(max(values))
    left, bottom, top = 40, 44, 26
    bw = (width - left - 10) / n
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="direction:ltr" role="img" aria-label="{html.escape(title)}">']
    if title:
        out.append(
            f'<text x="{width / 2}" y="16" text-anchor="middle" font-size="13" font-weight="bold" fill="currentColor">{html.escape(title)}</text>'
        )
    for k in range(5):
        y = top + (height - top - bottom) * k / 4
        out.append(f'<line x1="{left}" x2="{width - 8}" y1="{y:.1f}" y2="{y:.1f}" stroke="#8884" stroke-width="1"/>')
        out.append(
            f'<text x="{left - 4}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="currentColor" opacity=".7">{_tick(vmax * (1 - k / 4), fmt)}</text>'
        )
    for i, (lab, v) in enumerate(zip(labels, values)):
        h = (height - top - bottom) * (v / vmax)
        x = left + i * bw + bw * 0.15
        y = height - bottom - h
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw * 0.7:.1f}" height="{h:.1f}" fill="{color}" rx="2"/>')
        out.append(f'<text x="{x + bw * 0.35:.1f}" y="{y - 3:.1f}" text-anchor="middle" font-size="10" fill="currentColor">{fmt.format(v)}</text>')
        out.append(
            f'<text x="{x + bw * 0.35:.1f}" y="{height - bottom + 14}" text-anchor="middle" font-size="10" fill="currentColor">{html.escape(str(lab))[:14]}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def scatter_svg(groups, title="", width=620, height=420, legend=True):
    """خريطة نقطية مبسطة بإحداثيات مسقطة: groups = [{name, x, y, color, r, alpha}] (بدون خلفية خرائط)."""
    xs = np.concatenate([np.asarray(g["x"], float) for g in groups if len(g["x"])] or [np.array([0.0])])
    ys = np.concatenate([np.asarray(g["y"], float) for g in groups if len(g["y"])] or [np.array([0.0])])
    pad = 14
    sx = (width - 2 * pad) / max(np.ptp(xs), 1)
    sy = (height - 2 * pad - 20) / max(np.ptp(ys), 1)
    s = min(sx, sy)
    ox, oy = xs.min(), ys.min()
    out = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="direction:ltr" role="img" aria-label="{html.escape(title)}"><rect width="100%" height="100%" fill="#8881" rx="6"/>'
    ]
    if title:
        out.append(
            f'<text x="{width / 2}" y="16" text-anchor="middle" font-size="13" font-weight="bold" fill="currentColor">{html.escape(title)}</text>'
        )
    for g in groups:
        for x, y in zip(g["x"], g["y"]):
            out.append(
                f'<circle cx="{pad + (x - ox) * s:.1f}" cy="{height - pad - (y - oy) * s:.1f}" r="{g.get("r", 3)}" fill="{g["color"]}" fill-opacity="{g.get("alpha", 0.8)}"/>'
            )
    if legend:
        for i, g in enumerate(groups):
            out.append(
                f'<circle cx="{width - 14}" cy="{34 + i * 18}" r="5" fill="{g["color"]}"/><text x="{width - 24}" y="{38 + i * 18}" text-anchor="end" font-size="11" fill="currentColor">{html.escape(g["name"])}</text>'
            )
    out.append("</svg>")
    return "".join(out)


def _table(df, max_rows=40):
    d = DICT.relabel(df.head(max_rows))
    heads = "".join(f"<th>{html.escape(str(c))}</th>" for c in d.columns)
    rows = []
    for rec in d.itertuples(index=False):
        cells = []
        for v in rec:
            if isinstance(v, float):
                v = "—" if (math.isnan(v) or math.isinf(v)) else (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}".rstrip("0").rstrip("."))
            elif isinstance(v, (bool, np.bool_)):
                v = "نعم" if v else "لا"
            txt = html.escape(str(v))
            if re.search(r"\d", txt) and not re.search(r"[\u0600-\u06FF]", txt):
                txt = f'<bdi dir="ltr">{txt}</bdi>'  # أرقام وأوقات: لا تنعكس داخل خلية RTL
            cells.append(f"<td>{txt}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    more = f'<p class="note">يُعرض أول {max_rows} من {len(df)} صفاً. النسخة الكاملة في ملف Excel.</p>' if len(df) > max_rows else ""
    return f"<table><tr>{heads}</tr>{''.join(rows)}</table>{more}"


def build(meta, sections):
    """sections: قائمة dict اختيارية المفاتيح: title, intro, kpis [(قيمة, عنوان, صنف)], table (DataFrame), bars (labels, values, title), map (groups, title), notes [..]."""
    parts = [
        f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(meta['title'])}</title><style>{CSS}</style></head><body>"
    ]
    parts.append(
        f"<h1>{html.escape(meta['title'])}</h1><p class='sub'>{meta['generated']} · الإصدار {meta['version']} · بصمة {meta['fingerprint']}</p>"
    )
    if meta.get("demo"):
        parts.append('<div class="warn">⚠ هذا التقرير مبني على بيانات تجريبية اصطناعية، ولا يمثل واقعاً.</div>')
    for i, s in enumerate(sections):
        parts.append(f'<h2 class="{"pb" if i and s.get("page_break") else ""}">{html.escape(s["title"])}</h2>')
        if s.get("intro"):
            parts.append(f"<p>{html.escape(s['intro'])}</p>")
        if s.get("kpis"):
            parts.append(
                '<div class="kpis">'
                + "".join(
                    f'<div class="kpi {k[2] if len(k) > 2 else ""}"><b>{html.escape(str(k[0]))}</b><span>{html.escape(str(k[1]))}</span></div>'
                    for k in s["kpis"]
                )
                + "</div>"
            )
        if s.get("bars"):
            parts.append(bar_svg(*s["bars"][:2], title=s["bars"][2] if len(s["bars"]) > 2 else ""))
        if s.get("map"):
            parts.append(scatter_svg(s["map"]["groups"], s["map"].get("title", "")))
        if s.get("table") is not None and len(s["table"]):
            parts.append(_table(s["table"]))
        for n in s.get("notes", []):
            parts.append(f'<p class="note">• {html.escape(n)}</p>')
    meta_rows = "".join(f"<li>{html.escape(str(k))}: {html.escape(str(v))}</li>" for k, v in meta.get("params", {}).items())
    ds = "".join(
        f"<li>{html.escape(k)}: {v.get('rows', '')} سجل — {html.escape(str(v.get('loaded', '')))}</li>" for k, v in meta.get("datasets", {}).items()
    )
    parts.append(
        f'<div class="meta"><b>المعاملات</b><ul>{meta_rows}</ul><b>مصادر البيانات</b><ul>{ds}</ul><b>تنبيهات</b><ul>'
        + "".join(f"<li>{html.escape(d)}</li>" for d in meta.get("disclaimers", []) + meta.get("notes", []))
        + "</ul></div></body></html>"
    )
    return "".join(parts)
