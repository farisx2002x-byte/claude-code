"""سيناريوهات حجم الأسطول: نعيد التخطيط بحدود رحلة مختلفة (بحث أقصر، بدون حفظ)."""
import pandas as pd

import config as C
from src import routes as RT


def run(df, net, schools_xy, problems=None, limits=None, log=print):
    limits = limits or C.SCENARIO_LIMITS
    rows = []
    problems = problems if problems is not None else {}
    for lim in limits:
        R, RS, SA, G, nores, _ = RT.plan_all(df, net, schools_xy, max_ride_min=lim,
                                             scale=C.SCENARIO_SEARCH_SCALE, save=False, log=lambda *_: None, cache=problems)
        rows.append(dict(حد_الرحلة_دقيقة=lim, مركبات=len(R), كبير=int((R.vk == "large").sum()),
                         متوسط=int((R.vk == "medium").sum()), فان=int((R.vk == "small").sum()),
                         طلاب_بدون_مسار=len(nores),
                         متوسط_الرحلة=float((R.longest_ride_min * R.students).sum() / max(R.students.sum(), 1))))
        log(f"سيناريو {lim} د: {rows[-1]['مركبات']} مركبة")
    return pd.DataFrame(rows)
