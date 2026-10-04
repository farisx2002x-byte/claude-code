"""تنسيق الواجهة: RTL للمحتوى الرئيسي فقط (ما نلمس شريط المضيف)، بطاقات ومؤشرات تعمل في الوضعين الفاتح والداكن."""
import html

CSS = """
<style>
[data-testid="stMainBlockContainer"] {direction: rtl; text-align: right;}
[data-testid="stMainBlockContainer"] [data-testid="stDataFrame"],
[data-testid="stMainBlockContainer"] [data-testid="stVegaLiteChart"],
[data-testid="stMainBlockContainer"] [data-testid="stDeckGlJsonChart"] {direction: ltr;}
.bus-head {display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:4px;}
.bus-head h2 {margin:0; font-size:1.5rem;}
.bus-sub {opacity:.7; font-size:.9rem; margin:0 0 12px;}
.bus-badge {border-radius:999px; padding:2px 12px; font-size:.8rem; border:1px solid rgba(128,128,128,.4);}
.bus-badge.demo {background:rgba(224,168,0,.18); border-color:#e0a800;}
.bus-steps {display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 16px;}
.bus-step {flex:1 1 130px; padding:8px 10px; border-radius:10px; border:1px solid rgba(128,128,128,.3);
           background:rgba(128,128,128,.06); font-size:.85rem;}
.bus-step b {display:block; font-size:.95rem;}
.bus-step.done {border-color:#2e9e4f; background:rgba(46,158,79,.12);}
.bus-step small {opacity:.65;}
.bus-kpis {display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:8px 0 16px;}
.bus-kpi {padding:12px 14px; border-radius:12px; border:1px solid rgba(128,128,128,.25); background:rgba(128,128,128,.06);}
.bus-kpi .v {font-size:1.6rem; font-weight:700; line-height:1.2;}
.bus-kpi .l {opacity:.7; font-size:.85rem;}
.bus-kpi.ok {border-right:4px solid #2e9e4f;} .bus-kpi.mid {border-right:4px solid #e0a800;} .bus-kpi.hard {border-right:4px solid #d1383d;}
.bus-in {display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:10px; margin-bottom:6px;
         border:1px solid rgba(128,128,128,.25);}
.bus-in.ok {border-color:#2e9e4f;} .bus-in.bad {border-color:#d1383d;} .bus-in.warn {border-color:#e0a800;}
.bus-in .t {flex:1;} .bus-in .t small {display:block; opacity:.65;}
.bus-empty {text-align:center; padding:32px 12px; border:1px dashed rgba(128,128,128,.4); border-radius:14px; opacity:.85;}
.bus-note {font-size:.8rem; opacity:.65;}
</style>
"""


def kpi(value, label, cls=""):
    return f'<div class="bus-kpi {cls}"><div class="v">{html.escape(str(value))}</div><div class="l">{html.escape(label)}</div></div>'


def kpis(items):
    return '<div class="bus-kpis">' + "".join(kpi(*i) for i in items) + "</div>"
