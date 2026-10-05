"""مدينة تجريبية اصطناعية (8×8 كم): سكان، نقاط جذب، شبكة GTFS، ورحلات تاكسي. لمعاينة المنصة بدون بيانات حقيقية."""
import numpy as np
import pandas as pd

LON0, LAT0 = 39.17, 21.54       # قرب جدة
KM_LON = 111.32 * np.cos(np.radians(LAT0))
KM_LAT = 110.57
N = 16                          # 16×16 منطقة
CELL_KM = 0.5

CATS = {"مستشفى": 5, "جامعة": 3, "مول": 4, "سوق": 5, "مدرسة": 14, "مسجد": 16, "مبنى حكومي": 5, "مكاتب": 6, "ترفيه": 3, "محطة قطار": 2}


def _lonlat(xkm, ykm):
    return LON0 + (np.asarray(xkm) - N * CELL_KM / 2) / KM_LON, LAT0 + (np.asarray(ykm) - N * CELL_KM / 2) / KM_LAT


def population(seed=7):
    rng = np.random.default_rng(seed)
    ii, jj = np.meshgrid(np.arange(N), np.arange(N))
    ii, jj = ii.ravel(), jj.ravel()
    xk, yk = (ii + 0.5) * CELL_KM, (jj + 0.5) * CELL_KM
    centers = [(2.0, 2.5, 1.4), (6.0, 5.5, 1.8), (4.0, 6.5, 1.2)]
    dens = np.zeros(len(ii))
    for cx, cy, s in centers:
        dens += np.exp(-((xk - cx) ** 2 + (yk - cy) ** 2) / (2 * s ** 2))
    pop = (dens * 3500 * rng.uniform(0.7, 1.3, len(ii))).astype(int) + rng.integers(0, 200, len(ii))
    lon, lat = _lonlat(xk, yk)
    block = (ii // 4) * 4 + (jj // 4)
    return pd.DataFrame({"zone_id": [f"Z{k:03d}" for k in range(len(ii))], "name": [f"منطقة {k}" for k in range(len(ii))],
                         "district": [f"حي {b + 1}" for b in block], "pop": pop, "jobs": (dens * 900).astype(int),
                         "students": (pop * 0.18).astype(int), "low_income": np.clip(1 - dens / dens.max() + rng.normal(0, .1, len(ii)), 0, 1).round(2),
                         "lon": lon, "lat": lat})


def pois(seed=11):
    rng = np.random.default_rng(seed)
    rows = []
    for cat, n in CATS.items():
        for k in range(n):
            xk, yk = rng.uniform(0.3, N * CELL_KM - 0.3, 2)
            lon, lat = _lonlat(xk, yk)
            rows.append(dict(name=f"{cat} {k + 1}", category=cat, lon=float(lon), lat=float(lat)))
    return pd.DataFrame(rows)


def _line_points(p0, p1, spacing_km=0.6):
    d = np.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(int(d // spacing_km), 1)
    t = np.linspace(0, 1, n + 1)
    return [(p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a) for a in t]


def gtfs_feed():
    """5 خطوط حافلات: أفقيان وعموديان وقطري. ترددات: ذروة 10 د / عادي 20 د، من 06:00 لين 22:00."""
    W = N * CELL_KM
    lines = {
        "R1": ("الخط الأفقي الجنوبي", (0.3, 2.0), (W - 0.3, 2.3)),
        "R2": ("الخط الأفقي الشمالي", (0.3, 5.8), (W - 0.3, 6.1)),
        "R3": ("الخط العمودي الغربي", (2.0, 0.3), (2.2, W - 0.3)),
        "R4": ("الخط العمودي الشرقي", (5.8, 0.3), (6.0, W - 0.3)),
        "R5": ("الخط القطري", (0.5, 0.5), (W - 0.5, W - 0.5)),
    }
    stops, routes, trips, st_rows = {}, [], [], []
    for rid, (name, a, b) in lines.items():
        routes.append(dict(route_id=rid, route_short_name=rid, route_long_name=name, route_type=3))
        pts = _line_points(a, b)
        ids = []
        for k, p in enumerate(pts):
            key = (round(p[0], 2), round(p[1], 2))
            sid = f"S_{rid}_{k}"
            stops[sid] = key
            ids.append(sid)
        for direction, seq in ((0, ids), (1, ids[::-1])):
            t = 6 * 3600
            while t < 22 * 3600:
                tid = f"{rid}_{direction}_{t}"
                trips.append(dict(route_id=rid, service_id="WK", trip_id=tid, direction_id=direction))
                cur = t
                prev = None
                for seqno, sid in enumerate(seq):
                    if prev is not None:
                        d = np.hypot(stops[sid][0] - stops[prev][0], stops[sid][1] - stops[prev][1])
                        cur += int(d / 20 * 3600)       # 20 كم/س
                    st_rows.append(dict(trip_id=tid, arrival_time=_t(cur), departure_time=_t(cur + 30), stop_id=sid, stop_sequence=seqno))
                    cur += 30
                    prev = sid
                hour = t // 3600
                t += (10 if hour in (6, 7, 8, 14, 15, 16, 17) else 20) * 60
    sx = np.array([stops[s][0] for s in stops]); sy = np.array([stops[s][1] for s in stops])
    lon, lat = _lonlat(sx, sy)
    stops_df = pd.DataFrame({"stop_id": list(stops), "stop_name": [f"محطة {s}" for s in stops], "stop_lat": lat, "stop_lon": lon})
    cal = pd.DataFrame([dict(service_id="WK", monday=1, tuesday=1, wednesday=1, thursday=1, friday=0, saturday=0, sunday=1,
                             start_date="20250101", end_date="20251231")])
    return dict(stops=stops_df, routes=pd.DataFrame(routes), trips=pd.DataFrame(trips), stop_times=pd.DataFrame(st_rows), calendar=cal)


def _t(sec):
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def taxi_trips(n=6000, seed=3):
    """رحلات أسبوع: الالتقاط من السكان صباحاً ومن نقاط الجذب مساءً، مع نمط ساعات وأيام."""
    rng = np.random.default_rng(seed)
    pop, poi = population(), pois()
    pw = pop["pop"].values / pop["pop"].sum()
    cw = poi["category"].map({"مول": 4, "مستشفى": 3, "جامعة": 3, "محطة قطار": 5, "سوق": 2}).fillna(1).values
    cw = cw / cw.sum()
    hour_p = np.array([1, 1, 1, 1, 1, 2, 4, 8, 9, 6, 5, 5, 6, 6, 5, 5, 6, 8, 9, 8, 6, 4, 3, 2], float)
    hour_p /= hour_p.sum()
    hours = rng.choice(24, n, p=hour_p)
    days = rng.integers(0, 7, n)
    from_pop = (hours < 12) | (rng.random(n) < 0.35)
    zi = rng.choice(len(pop), n, p=pw)
    pi = rng.choice(len(poi), n, p=cw)
    plon = np.where(from_pop, pop["lon"].values[zi], poi["lon"].values[pi]) + rng.normal(0, 0.0012, n)
    plat = np.where(from_pop, pop["lat"].values[zi], poi["lat"].values[pi]) + rng.normal(0, 0.0012, n)
    di = rng.choice(len(poi), n, p=cw)
    zj = rng.choice(len(pop), n, p=pw)
    dlon = np.where(from_pop, poi["lon"].values[di], pop["lon"].values[zj])
    dlat = np.where(from_pop, poi["lat"].values[di], pop["lat"].values[zj])
    km = np.hypot((dlon - plon) * KM_LON, (dlat - plat) * KM_LAT) * 1.3 + 0.5
    base = pd.Timestamp("2025-03-02")
    t = base + pd.to_timedelta(days, "D") + pd.to_timedelta(hours * 60 + rng.integers(0, 60, n), "min")
    return pd.DataFrame({"pickup_time": t, "pickup_lon": plon, "pickup_lat": plat, "dropoff_lon": dlon, "dropoff_lat": dlat,
                         "distance_km": km.round(2), "duration_min": (km / 25 * 60 + 3).round(1), "fare": (5 + 2.2 * km).round(2),
                         "vehicle_id": rng.integers(1, 81, n), "wait_min": rng.gamma(2.0, 3.0, n).round(1)})


def taxi_stands():
    return pd.DataFrame({"name": [f"موقف {k + 1}" for k in range(6)],
                         "lon": _lonlat(np.array([2.0, 6.0, 4.0, 1.0, 7.0, 4.0]), np.array([2.0, 5.5, 6.5, 6.0, 2.0, 1.0]))[0],
                         "lat": _lonlat(np.array([2.0, 6.0, 4.0, 1.0, 7.0, 4.0]), np.array([2.0, 5.5, 6.5, 6.0, 2.0, 1.0]))[1]})


def build_all():
    return dict(population=population(), poi=pois(), gtfs=gtfs_feed(), trips=taxi_trips(), stands=taxi_stands())


def avl_apc(feed_tables, seed=5, days=5):
    """بيانات تتبع وركاب اصطناعية على جدول GTFS التجريبي: تأخير يتراكم على طول الخط وأكثر في الذروة، مع تكدّس عشوائي، وركاب حسب الساعة."""
    rng = np.random.default_rng(seed)
    st, trips = feed_tables["stop_times"].copy(), feed_tables["trips"]
    st = st.merge(trips[["trip_id", "route_id"]], on="trip_id")
    def sec(s):
        h, m, x = s.split(":")
        return int(h) * 3600 + int(m) * 60 + int(x)
    st["sched"] = st["departure_time"].map(sec)
    keep = rng.random(st["trip_id"].nunique()) < 0.35            # عيّنة رحلات
    ids = st["trip_id"].unique()[keep]
    st = st[st["trip_id"].isin(ids)]
    avl_rows, apc_rows = [], []
    for day in range(days):
        date = (pd.Timestamp("2025-03-02") + pd.Timedelta(days=day)).date().isoformat()
        for tid, g in st.groupby("trip_id"):
            g = g.sort_values("stop_sequence")
            hour = g["sched"].iloc[0] // 3600
            rush = 1.6 if hour in (7, 8, 16, 17) else 1.0
            base = rng.normal(0, 40)
            drift = rng.gamma(2.0, 12 * rush, len(g)).cumsum() * rng.choice([0.4, 1.0, 1.6])
            act = g["sched"].to_numpy() + base + drift
            for sid, sc, ac, seq in zip(g["stop_id"], g["sched"], act, g["stop_sequence"]):
                avl_rows.append(dict(date=date, route_id=g["route_id"].iloc[0], trip_id=tid, stop_id=sid, scheduled=int(sc), actual=int(ac)))
            n = len(g)
            lam = (14 if hour in (7, 8, 16, 17) else 6) * np.sin(np.linspace(0.2, np.pi - 0.2, n)) + 1
            b = rng.poisson(lam)
            a = np.minimum(np.concatenate([[0], np.cumsum(b)[:-1] // 3]), rng.poisson(lam * 0.9))
            for sid, bb, aa in zip(g["stop_id"], b, a):
                apc_rows.append(dict(date=date, route_id=g["route_id"].iloc[0], trip_id=tid, stop_id=sid, boardings=int(bb), alightings=int(aa)))
    return pd.DataFrame(avl_rows), pd.DataFrame(apc_rows)


def vehicle_register(n=45, seed=9):
    rng = np.random.default_rng(seed)
    year = rng.integers(2012, 2025, n)
    odo = ((2025 - year) * rng.uniform(40_000, 70_000, n)).astype(int)
    last = odo - rng.integers(500, 14_000, n)
    ld = pd.Timestamp("2025-03-01") - pd.to_timedelta(rng.integers(5, 220, n), "D")
    return pd.DataFrame({"vehicle_id": range(n), "type": rng.choice(["باص كبير", "باص متوسط"], n, p=[0.8, 0.2]), "seats": rng.choice([72, 26], n, p=[0.8, 0.2]),
                         "year": year, "odometer_km": odo, "last_service_km": last, "last_service_date": ld.date})
