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
