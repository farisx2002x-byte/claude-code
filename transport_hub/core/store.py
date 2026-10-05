"""مساحة عمل على القرص: تحفظ وتقرأ مجموعات البيانات (الطلب، نقاط الجذب، GTFS، رحلات التاكسي...)."""

import json
import os
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_ROOT = Path(os.environ.get("TRANSPORT_HUB_WORKSPACE") or Path(__file__).resolve().parents[1] / "workspace")


class Workspace:
    def __init__(self, root=None):
        self.root = Path(root) if root else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, name, ext):
        return self.root / f"{name}.{ext}"

    def save_df(self, name, df):
        df.to_parquet(self._p(name, "parquet"))
        self._touch(name)

    def df(self, name):
        p = self._p(name, "parquet")
        return pd.read_parquet(p) if p.exists() else None

    def save_obj(self, name, obj):
        self._p(name, "pkl").write_bytes(pickle.dumps(obj))
        self._touch(name)

    def obj(self, name):
        p = self._p(name, "pkl")
        return pickle.loads(p.read_bytes()) if p.exists() else None

    def has(self, name):
        return self._p(name, "parquet").exists() or self._p(name, "pkl").exists()

    def _touch(self, name):
        idx = self.meta()
        idx[name] = datetime.now().isoformat(timespec="seconds")
        self._p("_meta", "json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")

    def meta(self):
        p = self._p("_meta", "json")
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def set_source(self, name, source):
        """يسجل مصدر مجموعة البيانات: "demo" (اصطناعي) أو "upload" (مرفوع من المستخدم)."""
        src = self.obj("_sources") or {}
        src[name] = source
        self.save_obj("_sources", src)

    def sources(self):
        return self.obj("_sources") or {}

    def is_demo(self):
        """True لو أي مجموعة بيانات محمّلة من المدينة التجريبية (فتُوسم المخرجات بتنبيه)."""
        return "demo" in self.sources().values()

    def log(self, event, **kw):
        """سجل تدقيق بسيط (JSONL): من/متى/ماذا."""
        with open(self._p("audit", "jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(time=datetime.now().isoformat(timespec="seconds"), event=event, **kw), ensure_ascii=False) + "\n")

    def audit(self, n=200):
        p = self._p("audit", "jsonl")
        if not p.exists():
            return pd.DataFrame(columns=["time", "event"])
        rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()[-n:]]
        return pd.DataFrame(rows)

    def clear(self):
        for p in self.root.glob("*"):
            if p.is_file():
                p.unlink()
