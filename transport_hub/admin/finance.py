"""التكاليف والعائد: تكلفة التشغيل السنوية، تكلفة الراكب، الانبعاثات، وترتيب المشاريع تحت ميزانية (حقيبة الظهر)."""

from dataclasses import dataclass


@dataclass
class VehicleCost:
    name: str
    capex: float  # سعر الشراء (ريال)
    life_years: float
    opex_km: float  # وقود وصيانة لكل كم
    crew_hour: float  # أجر السائق/ساعة
    seats: int
    co2_kg_km: float


# قيم افتراضية تقديرية، تُعدّل من الواجهة
DEFAULT_COSTS = {
    "باص كبير": VehicleCost("باص كبير", 650_000, 12, 2.2, 28, 72, 0.9),
    "باص متوسط": VehicleCost("باص متوسط", 330_000, 10, 1.4, 25, 26, 0.55),
    "فان": VehicleCost("فان", 140_000, 8, 0.9, 22, 14, 0.3),
    "تاكسي": VehicleCost("تاكسي", 95_000, 6, 0.55, 20, 4, 0.2),
}


def annual_cost(vehicle, n_vehicles, km_day, hours_day, days=300, interest=0.05):
    """التكلفة السنوية (استهلاك رأسمالي بالقسط + تشغيل + طاقم)."""
    c = DEFAULT_COSTS[vehicle] if isinstance(vehicle, str) else vehicle
    r, n = interest, c.life_years
    crf = r * (1 + r) ** n / ((1 + r) ** n - 1)  # عامل استرداد رأس المال
    cap = n_vehicles * c.capex * crf
    ops = km_day * days * c.opex_km
    crew = hours_day * days * c.crew_hour
    return dict(capital=cap, operating=ops, crew=crew, total=cap + ops + crew, co2_t=km_day * days * c.co2_kg_km / 1000)


def cost_per_passenger(total_cost, pax_per_day, days=300):
    return total_cost / max(pax_per_day * days, 1)


def prioritize(projects, budget):
    """ترتيب المشاريع تحت ميزانية: يعظم مجموع الفائدة (مثلاً السكان المخدومين) بحل حقيبة الظهر الدقيق (CP-SAT).
    projects: DataFrame(name, cost, benefit). يرجع (المختار، غير المختار)."""
    from ortools.sat.python import cp_model

    p = projects.reset_index(drop=True)
    m = cp_model.CpModel()
    x = [m.NewBoolVar(f"x{i}") for i in range(len(p))]
    m.Add(sum(int(round(c)) * xi for c, xi in zip(p["cost"], x)) <= int(budget))
    m.Maximize(sum(int(round(b)) * xi for b, xi in zip(p["benefit"], x)))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 10
    st = s.Solve(m)
    pick = [i for i in range(len(p)) if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) and s.Value(x[i])]
    chosen = p.loc[pick].copy()
    chosen["benefit_per_cost"] = chosen["benefit"] / chosen["cost"]
    rest = p.drop(pick).copy()
    rest["benefit_per_cost"] = rest["benefit"] / rest["cost"]
    return chosen.sort_values("benefit_per_cost", ascending=False), rest.sort_values("benefit_per_cost", ascending=False)
