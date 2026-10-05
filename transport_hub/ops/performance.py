"""الأداء الفعلي من بيانات التتبع (AVL) وعدّادات الركاب (APC): الالتزام بالمواعيد، انتظام التردد، التكدّس، ومعايرة الركاب."""

import numpy as np
import pandas as pd

EARLY_S, LATE_S = 60, 300  # مبكر > دقيقة، متأخر > 5 دقائق (التعريف الشائع للالتزام)
AVL_COLS = ["date", "route_id", "trip_id", "stop_id", "scheduled", "actual"]
APC_COLS = ["date", "route_id", "trip_id", "stop_id", "boardings", "alightings"]


def _sec(s):
    """وقت HH:MM:SS (يقبل > 24 ساعة) أو رقم ثواني → ثواني."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    from transport_hub.transit.gtfs import parse_time

    return parse_time(s)


def clean_avl(df):
    miss = [c for c in AVL_COLS if c not in df.columns]
    if miss:
        raise ValueError(f"ملف التتبع AVL: أعمدة ناقصة {miss}. المطلوب {AVL_COLS}")
    d = df.copy()
    d["sched"], d["act"] = _sec(d["scheduled"]), _sec(d["actual"])
    d = d.dropna(subset=["sched", "act"])
    d["delay_s"] = d["act"] - d["sched"]
    d["hour"] = (d["sched"] // 3600).astype(int)
    return d.reset_index(drop=True)


def clean_apc(df):
    miss = [c for c in APC_COLS if c not in df.columns]
    if miss:
        raise ValueError(f"ملف الركاب APC: أعمدة ناقصة {miss}. المطلوب {APC_COLS}")
    d = df.copy()
    for c in ("boardings", "alightings"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    return d


def on_time(avl, by="route_id"):
    """نسبة الالتزام بالمواعيد: مبكر/في الموعد/متأخر، ومتوسط التأخير."""
    g = avl.assign(early=avl["delay_s"] < -EARLY_S, late=avl["delay_s"] > LATE_S).groupby(by)
    out = g.agg(
        observations=("delay_s", "size"),
        early_pct=("early", "mean"),
        late_pct=("late", "mean"),
        avg_delay_min=("delay_s", lambda s: s.mean() / 60),
        p90_delay_min=("delay_s", lambda s: s.quantile(0.9) / 60),
    )
    out["on_time_pct"] = 1 - out["early_pct"] - out["late_pct"]
    for c in ("early_pct", "late_pct", "on_time_pct"):
        out[c] = (out[c] * 100).round(1)
    return out.round(2).reset_index()


def headway_regularity(avl, sched_headway=None, min_obs=3):
    """انتظام التردد لكل (خط، محطة، يوم): الانتظار الإضافي EWT = AWT − SWT حيث AWT = Σh²/(2Σh). بالدقائق.
    التكدّس: تردد فعلي < 25% من المجدول. الفجوات: > 150%. sched_headway: dict route→دقائق (لو غاب نستخدمه من الجدول الفعلي)."""
    rows = []
    for (rid, sid, dt), g in avl.groupby(["route_id", "stop_id", "date"]):
        if len(g) < min_obs:
            continue
        a = np.sort(g["act"].to_numpy())
        s = np.sort(g["sched"].to_numpy())
        h = np.diff(a) / 60
        hs = np.diff(s) / 60
        shw = (sched_headway or {}).get(rid, float(np.mean(hs)))
        awt = (h**2).sum() / (2 * h.sum()) if h.sum() > 0 else np.nan
        swt = (hs**2).sum() / (2 * hs.sum()) if hs.sum() > 0 else np.nan
        rows.append(
            dict(
                route_id=rid,
                stop_id=sid,
                date=dt,
                headways=len(h),
                ewt_min=awt - swt,
                bunched_pct=100 * float(np.mean(h < 0.25 * shw)),
                gap_pct=100 * float(np.mean(h > 1.5 * shw)),
            )
        )
    d = pd.DataFrame(rows)
    if d.empty:
        return d, d
    by_route = (
        d.groupby("route_id")
        .agg(ewt_min=("ewt_min", "mean"), bunched_pct=("bunched_pct", "mean"), gap_pct=("gap_pct", "mean"))
        .round(2)
        .reset_index()
    )
    return d, by_route


def delay_profile(avl):
    """التأخير حسب الساعة (يكشف ساعات الذروة المتأزمة)."""
    return (
        avl.groupby("hour")["delay_s"]
        .agg(avg_delay_min=lambda s: s.mean() / 60, p90_delay_min=lambda s: s.quantile(0.9) / 60, observations="size")
        .round(2)
        .reset_index()
    )


def running_time(avl, feed, pct=85):
    """زمن الرحلة الفعلي (النسبة المئوية pct) مقابل المجدول لكل خط: توصية بتعديل الجدول (وقت زائد/ناقص)."""
    st = feed.stop_times[["trip_id", "stop_id", "stop_sequence"]]
    a = avl.merge(st, on=["trip_id", "stop_id"])
    g = a.sort_values("stop_sequence").groupby(["route_id", "trip_id", "date"])
    t = g.agg(sched=("sched", lambda s: s.max() - s.min()), act=("act", lambda s: s.max() - s.min()), n=("stop_id", "size"))
    t = t[t["n"] >= 3]
    out = t.groupby("route_id").agg(
        sched_min=("sched", lambda s: s.mean() / 60),
        actual_avg_min=("act", lambda s: s.mean() / 60),
        actual_pctl_min=("act", lambda s: s.quantile(pct / 100) / 60),
    )
    out["recommended_extra_min"] = (out["actual_pctl_min"] - out["sched_min"]).round(1)
    return out.round(1).reset_index()


def apc_summary(apc, seats=None, days=None):
    """ركاب كل خط (يومياً)، الحمل الأقصى لكل رحلة (تراكم الصعود − النزول)، ونسبة الرحلات المزدحمة (حمل > 90% من المقاعد)."""
    d = apc.sort_values(["date", "trip_id"]).copy()
    nd = days or max(d["date"].nunique(), 1)
    d["net"] = d["boardings"] - d["alightings"]
    d["load"] = d.groupby(["date", "trip_id"])["net"].cumsum()
    tr = d.groupby(["date", "route_id", "trip_id"]).agg(boardings=("boardings", "sum"), max_load=("load", "max")).reset_index()
    out = tr.groupby("route_id").agg(pax_day=("boardings", lambda s: s.sum() / nd), avg_max_load=("max_load", "mean"), trips=("trip_id", "nunique"))
    if seats:
        cap = out.index.map(lambda r: seats.get(r, 72)) if isinstance(seats, dict) else seats
        out["crowded_trips_pct"] = [
            100 * float((tr[tr["route_id"] == r]["max_load"] > 0.9 * c).mean()) for r, c in zip(out.index, np.broadcast_to(cap, len(out)))
        ]
    return out.round(1).reset_index()


def calibrate(actual_by_route, estimated_by_route):
    """معاملات معايرة نموذج الركاب: الفعلي ÷ المقدّر لكل خط، والمعامل الكلي (وسيط). يُضرب به تقدير الحصة لاحقاً."""
    m = (
        actual_by_route[["route_id", "pax_day"]]
        .rename(columns={"pax_day": "actual"})
        .merge(estimated_by_route[["route_id", "pax_day"]].rename(columns={"pax_day": "estimated"}), on="route_id")
    )
    m["factor"] = m["actual"] / m["estimated"].replace(0, np.nan)
    return m, float(m["factor"].median())


def recommend(otp, runtime=None, regularity=None, apc=None, late_limit=25.0, bunch_limit=12.0, crowd_limit=5.0):
    """توصيات تشغيلية آلية من النتائج (تُقرأ كنقاط انطلاق للتحليل، لا كقرارات)."""
    rec = []
    for r in otp.itertuples():
        if r.late_pct > late_limit:
            extra = ""
            if runtime is not None and r.route_id in set(runtime["route_id"]):
                x = runtime.set_index("route_id").loc[r.route_id, "recommended_extra_min"]
                extra = f"؛ زمن الرحلة المجدول أقل من الفعلي (النسبة 85) بـ {x:.0f} د: فكّر بتمديد الجدول"
            rec.append(f"الخط {r.route_id}: تأخر {r.late_pct:.0f}% من المحطات (الحد {late_limit:.0f}%){extra}.")
    if regularity is not None and len(regularity):
        for r in regularity.itertuples():
            if r.bunched_pct > bunch_limit:
                rec.append(f"الخط {r.route_id}: تكدّس {r.bunched_pct:.0f}% من الفواصل (الحد {bunch_limit:.0f}%): طبّق ضبط التردد أو أولوية الإشارات.")
    if apc is not None and "crowded_trips_pct" in apc:
        for r in apc.itertuples():
            if r.crowded_trips_pct > crowd_limit:
                rec.append(
                    f"الخط {r.route_id}: {r.crowded_trips_pct:.0f}% من الرحلات مزدحمة (>90% من المقاعد): ارفع التردد أو استخدم مركبة أكبر في الذروة."
                )
    return rec or ["لا مؤشرات تجاوزت الحدود في البيانات الحالية."]
