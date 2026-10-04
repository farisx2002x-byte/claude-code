import numpy as np
import pandas as pd

import config as C
from src import network as NW
from src import routes as RT


def grid_net(n=11, step=100.0):
    xy = np.array([[i * step, j * step] for i in range(n) for j in range(n)], float)
    U, V = [], []
    for i in range(n):
        for j in range(n):
            a = i * n + j
            if i + 1 < n:
                U += [a, (i + 1) * n + j]; V += [(i + 1) * n + j, a]
            if j + 1 < n:
                U += [a, i * n + j + 1]; V += [i * n + j + 1, a]
    U, V = np.array(U), np.array(V)
    L = np.full(len(U), step)
    T = L / (30 * C.PEAK_FACTOR / 3.6)
    geoms = [np.array([xy[u], xy[v]]) for u, v in zip(U, V)]
    return NW.Network(xy, U, V, L, T, np.full(len(U), 20.0), np.arange(len(U)), np.ones(len(U), bool), geoms)


def test_speed_by_width():
    assert NW.speed_kmh_measured(35, False) == 50
    assert NW.speed_kmh_measured(22, False) == 40
    assert NW.speed_kmh_measured(15, False) == 30
    assert NW.speed_kmh_measured(11, False) == 20
    assert NW.speed_kmh_measured(8, False) == 12
    assert NW.speed_kmh_measured(8, True) == 45


def test_merge_stops_close_and_split():
    xy = np.array([[0, 0], [20, 0], [500, 0]], float)
    st = RT.merge_stops(xy, np.array(["small"] * 3), [10, 11, 12])
    assert sorted(len(s["students"]) for s in st) == [1, 2]
    xy = np.zeros((30, 2))
    st = RT.merge_stops(xy, np.array(["small"] * 30), list(range(30)))
    assert sorted(len(s["students"]) for s in st) == [6, 12, 12]
    ids = [i for s in st for i in s["students"]]
    assert sorted(ids) == list(range(30))          # بدون تكرار


def test_small_vrp_capacity_and_coverage():
    net = grid_net()
    # 30 طالب فان ÷ 12 = 3 مركبات كحد أدنى
    pts = [(x, y) for x, y in [(200, 0), (300, 0), (400, 0), (0, 200), (0, 300), (0, 400),
                               (300, 300), (400, 400), (500, 200), (200, 500)]]
    rows = []
    for k, (x, y) in enumerate(pts):
        for j in range(3):
            rows.append(dict(idx=len(rows), board_x=x, board_y=y, rec_vehicle="small", school_official="م"))
    df = pd.DataFrame(rows)
    P = RT.prepare_school("م", df, net, (0.0, 0.0))
    sol = RT.solve(P, max_ride_min=60, scale=0.5, seed_time=3)
    assert sol["dropped"] == []
    R, RS, SA, G = RT.finalize(P, sol, net, (0.0, 0.0), save_geometry=True)
    assert len(SA) == 30 and SA.idx.nunique() == 30
    assert (R.vk == "small").all()
    assert (R.students <= RT.cap_of("small")).all()
    assert len(R) >= 3
    assert len(R) <= 4
    assert (R.longest_ride_min <= 60 * C.HARD_RIDE_FACTOR + 1).all()


def test_big_stop_not_served_by_bigger_vehicle_than_recommended():
    net = grid_net()
    df = pd.DataFrame([dict(idx=i, board_x=300.0, board_y=300.0, rec_vehicle="small", school_official="م")
                       for i in range(8)])
    P = RT.prepare_school("م", df, net, (0.0, 0.0))
    sol = RT.solve(P, scale=0.5, seed_time=3)
    assert all(r["vk"] == "small" for r in sol["routes"])
