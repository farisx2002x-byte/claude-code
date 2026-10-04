# -*- coding: utf-8 -*-
"""صندوق أدوات ArcGIS Pro: تحليل وصول الباص وتخطيط المسارات (النقل المدرسي — جدة).
بيئة ArcGIS Pro ما فيها rasterio وskan وortools، فالأداة تشغّل run.py ببيئة conda منفصلة (busaccess)."""
import glob
import importlib.util
import os
import subprocess
import sys

import arcpy

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = ["all", "load", "tiles", "network", "score", "routes", "scenarios", "export", "report"]


def _find_python():
    """تخمين بايثون بيئة busaccess في anaconda3 / miniconda3 / miniforge3 وغيرها."""
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("anaconda3", "miniconda3", "miniforge3", "mambaforge", "Anaconda3", "Miniconda3")]
    roots += [os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), d) for d in ("anaconda3", "miniconda3")]
    for r in roots:
        for p in (os.path.join(r, "envs", "busaccess", "python.exe"), os.path.join(r, "envs", "busaccess", "bin", "python")):
            if os.path.exists(p):
                return p
    found = glob.glob(os.path.join(home, "*", "envs", "busaccess", "python.exe"))
    return found[0] if found else ""


def _load_layers_module():
    spec = importlib.util.spec_from_file_location("add_layers_arcgis", os.path.join(PROJECT, "arcgis", "add_layers_arcgis.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Toolbox(object):
    def __init__(self):
        self.label = "النقل المدرسي — جدة"
        self.alias = "BusAccess"
        self.tools = [RunAnalysis, AddLayers, OpenDashboard]


class RunAnalysis(object):
    def __init__(self):
        self.label = "تشغيل التحليل"
        self.description = "يشغّل run.py ببيئة conda (busaccess) ويبث السجل لرسائل الأداة."
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter("python_exe", "بايثون بيئة busaccess", "Input", "DEFile", "Required")
        p0.value = _find_python()
        p1 = arcpy.Parameter("step", "الخطوة", "Input", "GPString", "Required")
        p1.filter.type = "ValueList"
        p1.filter.list = STEPS
        p1.value = "report"
        p2 = arcpy.Parameter("data_dir", "مجلد البيانات", "Input", "DEFolder", "Required")
        p2.value = os.path.join(os.path.expanduser("~"), "Downloads")
        p3 = arcpy.Parameter("add_layers", "إضافة الطبقات بعد التشغيل", "Input", "GPBoolean", "Optional")
        p3.value = True
        return [p0, p1, p2, p3]

    def execute(self, parameters, messages):
        py, step, data_dir, add = [p.valueAsText for p in parameters]
        if not py or not os.path.exists(py):
            raise arcpy.ExecuteError("حدد بايثون بيئة busaccess (conda create -n busaccess ...)")
        env = dict(os.environ, BUS_DATA_DIR=data_dir, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([py, "run.py", step], cwd=PROJECT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, universal_newlines=True, encoding="utf-8")
        for line in proc.stdout:
            messages.addMessage(line.rstrip())
        if proc.wait() != 0:
            raise arcpy.ExecuteError("فشل التشغيل، راجع output/سجل_التشغيل.txt")
        if parameters[3].value:
            _load_layers_module().add_layers()


class AddLayers(object):
    def __init__(self):
        self.label = "إضافة الطبقات بألوانها"
        self.description = "يضيف الشوارع والعوائق والمسارات والوقفات والطلاب ونقاط التجميع والمدارس."
        self.canRunInBackground = False

    def getParameterInfo(self):
        p = arcpy.Parameter("gpkg", "ملف التحليل (gpkg)", "Input", "DEFile", "Required")
        p.value = os.path.join(PROJECT, "output", "تحليل_وصول_الباص.gpkg")
        return [p]

    def execute(self, parameters, messages):
        _load_layers_module().add_layers(parameters[0].valueAsText)


class OpenDashboard(object):
    def __init__(self):
        self.label = "فتح اللوحة"
        self.description = "يشغّل لوحة Streamlit في المتصفح."
        self.canRunInBackground = False

    def getParameterInfo(self):
        p = arcpy.Parameter("python_exe", "بايثون بيئة busaccess", "Input", "DEFile", "Required")
        p.value = _find_python()
        return [p]

    def execute(self, parameters, messages):
        py = parameters[0].valueAsText
        subprocess.Popen([py, "-m", "streamlit", "run", "app.py"], cwd=PROJECT)
        messages.addMessage("تم تشغيل اللوحة، تفتح في المتصفح (http://localhost:8501)")
