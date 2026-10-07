"""اختبار واجهة كل صفحة بـ AppTest على المدينة التجريبية: لا أخطاء، وتظهر العناصر المتوقعة."""

import pytest
from streamlit.testing.v1 import AppTest

ROOT = __file__.rsplit("/transport_hub/", 1)[0]
PAGES = ["p_home", "p_data", "p_transit", "p_taxi", "p_siting", "p_attractors", "p_admin"]


@pytest.fixture(scope="module")
def ws_env(tmp_path_factory):
    import os

    d = tmp_path_factory.mktemp("ws")
    os.environ["TRANSPORT_HUB_WORKSPACE"] = str(d)
    yield d
    os.environ.pop("TRANSPORT_HUB_WORKSPACE", None)


def script(page, demo=True):
    return f"""
import sys; sys.path.insert(0, {ROOT!r})
import streamlit as st
from transport_hub.ui import common as U
from transport_hub.ui import p_data, {page}
if {demo!r} and U.get("population") is None:
    p_data.load_demo()
{page}.render()
"""


def test_empty_state_every_page(ws_env):
    for page in PAGES:
        if page == "p_data":
            continue
        at = AppTest.from_string(script(page, demo=False), default_timeout=120).run()
        assert not at.exception, (page, [e.value for e in at.exception])


@pytest.mark.parametrize("page", PAGES)
def test_page_with_demo_data(ws_env, page):
    at = AppTest.from_string(script(page), default_timeout=300).run()
    assert not at.exception, (page, [e.value for e in at.exception])
    assert len(at.markdown) > 0


def test_transit_planning_tabs_interact(ws_env):
    at = AppTest.from_string(script("p_transit"), default_timeout=300).run()
    at.radio(key="hub_t_plan").set_value("اقتراح خط جديد").run()
    assert not at.exception, [e.value for e in at.exception]
    at.radio(key="hub_t_plan").set_value("تعديل الترددات").run()
    assert not at.exception, [e.value for e in at.exception]


def test_siting_all_methods(ws_env):
    at = AppTest.from_string(script("p_siting"), default_timeout=300).run()
    for m in ["أقصى تغطية", "p-median (مراكز/مستودعات)", "معايير متعددة (MCDA)"]:
        at.selectbox(key="hub_s_method").set_value(m).run()
        assert not at.exception, (m, [e.value for e in at.exception])
    for kind in ["موقف تاكسي", "مستودع حافلات"]:
        at.selectbox(key="hub_s_kind").set_value(kind).run()
        assert not at.exception, (kind, [e.value for e in at.exception])


@pytest.mark.parametrize("page", ["p_ops", "p_perf"])
def test_ops_pages_with_demo_data(ws_env, page):
    at = AppTest.from_string(script(page), default_timeout=300).run()
    assert not at.exception, (page, [e.value for e in at.exception])
    assert len(at.markdown) > 0


def test_outputs_page_builds_package(ws_env):
    at = AppTest.from_string(script("p_outputs"), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.markdown) > 0


def test_guard_shows_friendly_error():
    code = f"""
import sys; sys.path.insert(0, {ROOT!r})
from transport_hub.ui import common as U
@U.guard
def bad():
    raise RuntimeError("boom")
bad()
"""
    at = AppTest.from_string(code, default_timeout=60).run()
    assert not at.exception
    assert any("حدث خطأ غير متوقع" in m.value for m in at.markdown)


def test_roads_toggle_switches_distance_mode(ws_env):
    at = AppTest.from_string(script("p_transit"), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    texts = " ".join(c.value for c in at.caption)
    assert "OSM" in texts  # المدينة التجريبية فيها شوارع: الوضع الافتراضي شبكة فعلية
    at.toggle(key="hub_use_roads").set_value(False).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "تقدير" in " ".join(c.value for c in at.caption)


def test_data_page_roads_tab_status(ws_env):
    at = AppTest.from_string(script("p_data"), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("حالة شبكة الشوارع" in m.value for m in at.markdown)


def test_congestion_toggle_changes_status(ws_env):
    at = AppTest.from_string(script("p_transit"), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "تعلّم" in " ".join(c.value for c in at.caption)  # التجريبية فيها ملف ازدحام متعلَّم
    at.toggle(key="hub_use_cong").set_value(False).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "غير مطبّق" in " ".join(c.value for c in at.caption)


def test_learn_congestion_button_flow(ws_env):
    at = AppTest.from_string(script("p_perf"), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    from transport_hub.core.store import Workspace

    Workspace().delete("congestion")
    at = AppTest.from_string(script("p_perf"), default_timeout=300).run()
    btn = next(b for b in at.button if b.key == "hub_c_learn")
    btn.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert Workspace().obj("congestion") is not None


def test_admin_scenario_comparison_view(ws_env):
    code = script("p_admin").replace(
        "p_admin.render()",
        """from transport_hub.admin.scenarios import ScenarioBook
b = ScenarioBook(U.ws())
b.save("أساس", {}, dict(covered_400_pct=30.0, covered_800_pct=60.0, avg_access_index=2.0, pop_no_service=1000))
b.save("خط جديد", {}, dict(covered_400_pct=40.0, covered_800_pct=65.0, avg_access_index=2.5, pop_no_service=700), cost=2000000)
p_admin.render()""",
    )
    at = AppTest.from_string(code, default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    at.selectbox(key="hub_ad_base").set_value("خط جديد").run()
    assert not at.exception, [e.value for e in at.exception]
