import io
import json
import subprocess

from transport_hub import __version__, cli
from transport_hub.admin.scenarios import ScenarioBook
from transport_hub.core import demo_city as DC
from transport_hub.core import geo
from transport_hub.core.store import Workspace
from transport_hub.transit import csa, gtfs


def test_version_single_source():
    from transport_hub.exports import meta

    assert meta.VERSION == __version__ == "1.4.0"
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(rf'^version = "{re.escape(__version__)}"', text, re.M)


def test_gtfs_zip_roundtrip():
    t = DC.gtfs_feed()
    buf = io.BytesIO()
    gtfs.write_zip(t, buf)
    f = gtfs.read_zip(buf.getvalue())
    assert len(f.stops) == len(t["stops"]) and len(f.trips) == len(t["trips"])
    assert gtfs.validate(f)["العدد"].sum() == 0
    assert gtfs.active_trips(f, weekday=4).empty  # الجمعة غير مفعّلة في تقويم التجربة
    assert len(gtfs.active_trips(f, weekday=0)) == len(f.trips)


def test_scenario_book(tmp_path):
    book = ScenarioBook(Workspace(tmp_path))
    book.save("أساس", {}, {"cov": 30.0})
    book.save("س2", {"x": 1}, {"cov": 40.0})
    cmp = book.compare()
    assert cmp.loc["س2", "Δ cov"] == 10.0
    assert ScenarioBook(Workspace(tmp_path)).data.keys() == {"أساس", "س2"}  # يُحفظ على القرص
    book.delete("س2")
    assert list(book.compare().index) == ["أساس"]


def test_audit_log(tmp_path):
    w = Workspace(tmp_path)
    w.log("a", x=1)
    w.log("b")
    assert list(w.audit()["event"]) == ["a", "b"]


def test_csa_opportunities_monotonic_in_time():
    d = DC.build_all()
    f = gtfs.from_tables(d["gtfs"])
    proj = geo.Projector.for_points(f.stops.stop_lon, f.stops.stop_lat)
    from transport_hub.core import data as D

    pop = D.clean_population(d["population"], proj)
    r = csa.Router(f, proj)
    o = pop.iloc[:6]
    a = csa.opportunities(r, o, pop, 8.0, 20, ("pop",), max_origins=6)["reach_pop_20"].to_numpy()
    b = csa.opportunities(r, o, pop, 8.0, 45, ("pop",), max_origins=6)["reach_pop_45"].to_numpy()
    assert (b >= a).all() and b.sum() > a.sum()  # وقت أطول = وصول أكثر


def test_cli_builds_streamlit_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "call", lambda cmd: seen.setdefault("cmd", cmd) and 0)
    assert cli.main(["--port", "9999", "--headless"]) == 0
    assert "streamlit" in seen["cmd"] and "9999" in seen["cmd"] and "app.py" in seen["cmd"][4]


def test_json_manifest_is_valid_utf8(tmp_path):
    from transport_hub.exports import meta

    m = meta.build("عنوان", {"م": 1}, {"س": {"rows": 1, "loaded": "x"}})
    assert json.loads(json.dumps(m, ensure_ascii=False))["title"] == "عنوان"


def test_logger_respects_env(monkeypatch):
    monkeypatch.setenv("TRANSPORT_HUB_LOG", "DEBUG")
    from transport_hub.core.log import get_logger

    assert get_logger("x").name == "transport_hub.x"


def _book(tmp_path):
    book = ScenarioBook(Workspace(tmp_path))
    book.save("أساس", {}, dict(covered_400_pct=30.0, covered_800_pct=60.0, avg_access_index=2.0, pop_no_service=1000))
    book.save("أ", {}, dict(covered_400_pct=40.0, covered_800_pct=65.0, avg_access_index=2.5, pop_no_service=700), cost=2_000_000)
    book.save("ب", {}, dict(covered_400_pct=35.0, covered_800_pct=60.0, avg_access_index=1.9, pop_no_service=1200))
    return book


def test_scenario_verdicts_follow_direction(tmp_path):
    d = _book(tmp_path).detailed()
    v = d.set_index(["scenario", "kpi"])["verdict"]
    assert v[("أ", "pop_no_service")] == "أفضل"  # الأقل أفضل
    assert v[("ب", "pop_no_service")] == "أسوأ"
    assert v[("ب", "covered_800_pct")] == "ثابت"


def test_scenario_rank_and_cost_effectiveness(tmp_path):
    book = _book(tmp_path)
    r = book.rank()
    assert book.best() == "أ" and r.loc["أ", "rank"] == 1 and r.loc["أ", "score_vs_base"] > 0
    assert r["score"].between(0, 100).all()
    ce = book.cost_effectiveness()
    assert ce.loc[ce.scenario == "أ", "cost_per_point"].iloc[0] == 200_000  # 2 مليون / 10 نقاط
    assert ce.loc[ce.scenario == "ب", "cost_per_point"].isna().all()  # بلا تكلفة
    book.set_cost("ب", 500_000)
    assert book.cost_effectiveness().set_index("scenario").loc["ب", "cost_per_point"] == 100_000
    assert ScenarioBook(Workspace(tmp_path)).costs()["أ"] == 2_000_000


def test_scenario_rank_degenerate(tmp_path):
    book = ScenarioBook(Workspace(tmp_path))
    assert book.rank().empty and book.best() is None and book.detailed().empty
    book.save("وحيد", {}, dict(covered_400_pct=10.0))
    assert book.rank().loc["وحيد", "score"] == 50.0  # لا نطاق للتطبيع
