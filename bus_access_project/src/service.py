"""واجهة الخدمة (بدون Streamlit): حالة المدخلات والخطوات، تشغيل الخطوات، وقراءة النتائج.
أي تطبيق مضيف (Streamlit أو Flask أو FastAPI...) يقدر يستخدمها مباشرة."""
import os
import pickle
import subprocess
import sys
from pathlib import Path

import config as C
from src import inputs

STEPS = [  # (المفتاح, العنوان, ملف الحالة, الخطوات اللي لازم تكون جاهزة قبلها)
    ("load", "قراءة البيانات", "students.parquet", []),
    ("tiles", "تحليل الشوارع", "res_raw.pkl", ["load"]),
    ("network", "الشبكة", "network.pkl", ["tiles"]),
    ("score", "التصنيف والأسطول", "res_scored.pkl", ["tiles"]),
    ("routes", "المسارات والتصدير", "routes.pkl", ["score", "network"]),
    ("scenarios", "السيناريوهات", "scenarios.pkl", ["routes"]),
]
DEMO_DIR = C.PROJECT / "demo_state"


def dirs(demo=False):
    """(work, output) للوضع الحقيقي أو التجريبي."""
    return (DEMO_DIR / "work", DEMO_DIR / "output") if demo else (C.PROJECT / "work", C.PROJECT / "output")


def pipeline_state(demo=False):
    """حالة كل خطوة: done + وقت آخر تحديث."""
    work, _ = dirs(demo)
    res, done = [], set()
    for key, title, f, _pre in STEPS:
        p = work / f
        ok = p.exists()
        if ok:
            done.add(key)
        res.append(dict(key=key, title=title, done=ok, mtime=p.stat().st_mtime if ok else None))
    return res


def missing_prereq(step, demo=False):
    """رسالة عربية لو الخطوة ما تقدر تشتغل (مدخلات أو خطوات ناقصة)، وإلا None."""
    if demo:
        return None
    st = {s["key"]: s["done"] for s in pipeline_state(False)}
    if step in ("load", "all"):
        miss = [s["label"] for s in inputs.status() if not s["found"]]
        return ("ملفات ناقصة: " + "، ".join(miss)) if miss else None
    pre = next((p for k, _t, _f, p in STEPS if k == step), [])
    miss = [t for k, t, _f, _p in STEPS if k in pre and not st.get(k)]
    return ("شغّل أولاً: " + "، ".join(miss)) if miss else None


def run_step(step, workers=None, fresh=False, demo=False, on_line=None):
    """يشغّل خطوة في عملية منفصلة ويبث السطور لـ on_line. يرجع رمز الخروج."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", BUS_DATA_DIR=str(inputs.data_dir()))
    if demo:
        env["BUS_DEMO_DIR"] = str(DEMO_DIR)
        DEMO_DIR.mkdir(exist_ok=True)
        cmd = [sys.executable, "-m", "src.demo_data"]
    else:
        env.pop("BUS_DEMO_DIR", None)
        cmd = [sys.executable, "run.py", step] + (["--workers", str(workers)] if workers else []) + (["--fresh"] if fresh else [])
    proc = subprocess.Popen(cmd, cwd=C.PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8")
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip())
    return proc.wait()


def load_pickle(name, demo=False):
    p = dirs(demo)[0] / name
    return pickle.loads(p.read_bytes()) if p.exists() else None


def results(demo=False):
    """كل النتائج المحفوظة (None لو ما انتهت الخطوة)."""
    return dict(scored=load_pickle("res_scored.pkl", demo), routes=load_pickle("routes.pkl", demo),
                scenarios=load_pickle("scenarios.pkl", demo), raw=load_pickle("res_raw.pkl", demo))


def output_files(demo=False):
    out = dirs(demo)[1]
    return sorted(p for p in out.glob("*") if p.is_file()) if out.exists() else []
