"""بيانات التوثيق المرفقة بكل مخرج: الإصدار، الوقت، المعاملات، مصادر البيانات، والتنبيهات (للتتبع وإعادة الإنتاج)."""

import hashlib
import json
from datetime import datetime

from transport_hub import __version__ as VERSION  # noqa: E402

DISCLAIMERS = [
    "المسافات في النقل العام والتاكسي مستقيمة × 1.3 (معامل تعرج تقديري) لا على شبكة شوارع.",
    "تقدير الركاب نموذج أولي يحتاج معايرة بعدّادات الركاب.",
    "الأرقام الاصطناعية (بيانات التجربة) لا تمثل واقعاً ولا تُستخدم لاتخاذ قرارات.",
]


def build(title, params=None, datasets=None, notes=None, demo=False):
    """datasets: dict اسم → {rows, loaded}. يضيف بصمة قصيرة من المعاملات والبيانات لتمييز التشغيلات."""
    params = params or {}
    datasets = datasets or {}
    fp = hashlib.sha1(json.dumps([params, datasets], sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:10]
    return dict(
        title=title,
        version=VERSION,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        fingerprint=fp,
        params=params,
        datasets=datasets,
        notes=(notes or []),
        disclaimers=DISCLAIMERS + (["⚠ هذا المخرج مبني على بيانات تجريبية اصطناعية."] if demo else []),
        demo=demo,
    )
