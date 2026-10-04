"""الأسطول الحالي مقابل الطلاب. نقرأ ثلاثة أعمدة بس (اسم المدرسة، المقاعد، النوع)؛
بيانات السائقين والمرافقين لا تُقرأ ولا تُنسخ."""
import math

import numpy as np
import pandas as pd

import config as C
from src import load_data as L

MEDIUM_SEATS_MAX = 40   # أقل من 40 مقعد = حافلة متوسطة


def read_fleet(path=None):
    df = pd.read_excel(path or C.FLEET_XLSX, usecols=["اسم المدرسة", "المقاعد", "النوع"])
    df["المقاعد"] = pd.to_numeric(df["المقاعد"], errors="coerce")
    df = df.dropna(subset=["المقاعد", "اسم المدرسة"])
    alias = L.load_fleet_alias()
    df["school"] = df["اسم المدرسة"].astype(str).str.strip().map(lambda s: alias.get(s, s))
    df["seats"] = df["المقاعد"].astype(int)
    df["type"] = df["النوع"].astype(str)
    df["cls"] = np.where(df["seats"] < MEDIUM_SEATS_MAX, "medium", "large")
    return df[["school", "seats", "type", "cls"]]


def by_school(df_students, fleet):
    """جدول لكل مدرسة رسمية."""
    g = df_students.groupby("school_official")
    out = pd.DataFrame({
        "students": g.size(),
        "hard_L": g["level_L"].apply(lambda s: int((s == "صعب").sum())),
        "rec_medium": g["rec_vehicle"].apply(lambda s: int((s == "medium").sum())),
        "rec_small": g["rec_vehicle"].apply(lambda s: int((s == "small").sum())),
        "rec_pickup": g["rec_vehicle"].apply(lambda s: int((s == "pickup").sum())),
        "median_dist_m": g["dist_school_m"].median(),
    })
    out.index.name = "school"
    fg = fleet.groupby("school")
    f = pd.DataFrame({
        "buses_large": fg["cls"].apply(lambda s: int((s == "large").sum())),
        "buses_medium": fg["cls"].apply(lambda s: int((s == "medium").sum())),
        "seats_large": fg.apply(lambda d: int(d.loc[d.cls == "large", "seats"].sum()), include_groups=False),
        "seats_medium": fg.apply(lambda d: int(d.loc[d.cls == "medium", "seats"].sum()), include_groups=False),
        "types": fg["type"].apply(lambda s: "، ".join(sorted(set(s)))),
    })
    out = out.join(f, how="outer").fillna({"buses_large": 0, "buses_medium": 0, "seats_large": 0,
                                           "seats_medium": 0, "students": 0, "hard_L": 0, "rec_medium": 0,
                                           "rec_small": 0, "rec_pickup": 0, "types": ""})
    out["need_medium"] = out["rec_medium"].map(lambda n: math.ceil(n / C.VEHICLES["medium"]["seats"]))
    out["shortage_medium"] = (out["need_medium"] - out["buses_medium"]).clip(lower=0)
    seats = out["seats_large"] + out["seats_medium"]
    out["seats_per_student"] = np.where(out["students"] > 0, seats / out["students"].replace(0, np.nan), np.nan)
    return out.reset_index()
