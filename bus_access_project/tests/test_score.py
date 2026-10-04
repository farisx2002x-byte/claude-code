import numpy as np
import pandas as pd

import config as C
from src import score as SC


def r(**k):
    d = dict(access=True, snap_m=5.0, walk_net_m=0.0, bottleneck_row=20.0, tight_turns=0, vtight_turns=0,
             reverse_m=0.0, narrow_len_m=0.0)
    d.update(k)
    return d


def test_easy():
    lv, sc, w, why, conf = SC.score_one(r(), "large", "سكني", False, "متوسط")
    assert lv == "سهل" and sc == 0 and conf == "عالية"


def test_no_access_is_hard():
    assert SC.score_one(r(access=False), "large", "", False, "ثانوي")[0] == "صعب"


def test_walk_young_factor_and_hard_override():
    # 190 م × 1.4 = 266 > 250 → صعب مباشرة
    lv = SC.score_one(r(walk_net_m=190.0), "large", "", False, "ابتدائي")[0]
    assert lv == "صعب"
    lv2 = SC.score_one(r(walk_net_m=190.0), "large", "", False, "ثانوي")[0]
    assert lv2 != "صعب"


def test_points_combine():
    # أضيق 9 م (3) + التفافين حادين (2) + رجوع 60 م (2) = 7 → صعب
    lv, sc, *_ = SC.score_one(r(bottleneck_row=9, tight_turns=2, reverse_m=60), "large", "", False, "ثانوي")
    assert sc == 7 and lv == "صعب"


def test_zone_points():
    assert SC.zone_points("سكني عشوائي") == 2
    assert SC.zone_points("المنطقة الصناعية التاريخية") == 2
    assert SC.zone_points("المستودعات") == 1
    assert SC.zone_points("سكني") == 0


def test_unknown_parcel_uses_network_walk_only_and_low_conf():
    lv, sc, w, why, conf = SC.score_one(r(snap_m=100.0, walk_net_m=10.0), "large", "", True, "ثانوي")
    assert w == 10.0 and conf == "منخفضة" and "تقديرية" in why


def test_recommend_and_pickup_ids():
    df = pd.DataFrame({"level_L": ["سهل", "صعب", "صعب", "صعب"], "level_M": ["سهل", "متوسط", "صعب", "صعب"],
                       "level_S": ["سهل", "سهل", "متوسط", "صعب"]})
    assert list(SC._recommend_vec(df)) == ["large", "small", "small", "pickup"]


def test_pickup_mapping_by_cluster_not_row_order():
    # طالبان قريبان (نفس المجموعة) وبينهم طالب بعيد؛ لازم الأول والثالث ياخذون نفس pickup_id
    df = pd.DataFrame({"access_L": [True] * 3, "walk_used_L": [100.0] * 3, "level_L": ["صعب"] * 3,
                       "stop_x_L": [0.0, 1000.0, 10.0], "stop_y_L": [0.0, 0.0, 0.0],
                       "school": ["أ", "ب", "أ"], "district": ["د"] * 3})
    out, pk = SC.build_pickups(df, "large")
    assert out.pickup_id.iat[0] == out.pickup_id.iat[2] != out.pickup_id.iat[1]
    assert len(pk) == 2 and pk.students.sum() == 3
