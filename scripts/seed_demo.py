"""Populate a database with plausible demo history so the dashboard has something to show.

Usage:
    python scripts/seed_demo.py                 # seeds MEDITRACK_DB_PATH (default data/meditrack.db)
    python scripts/seed_demo.py --days 45 --seed 7

The data goes through the same service layer as the UI, day by day in order, so
each appointment is scored using only the history that existed at that point.
Outcomes are random draws (each patient has a hidden reliability); nothing here is real.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.main import build_state  # noqa: E402
from app.schemas import AppointmentIn, AppointmentType, Status  # noqa: E402

FIRST = ["Asha", "Ravi", "Meera", "Karthik", "Priya", "Arjun", "Divya", "Sanjay", "Lakshmi", "Vikram",
         "Anitha", "Rahul", "Sneha", "Manoj", "Kavya", "Suresh", "Neha", "Rohit", "Pooja", "Harish"]
LAST = ["Reddy", "Nair", "Sharma", "Iyer", "Rao", "Menon", "Patel", "Gupta", "Naidu", "Das"]
TYPE_WEIGHTS = {"checkup": 30, "follow_up": 25, "specialist": 15, "vaccination": 10, "lab_test": 20}


def run(days: int, seed: int) -> None:
    rng = random.Random(seed)
    settings = Settings.from_env()
    state = build_state(settings)
    if state.appointments_repo.count() > 0:
        print("Database already has appointments; refusing to seed on top of them.")
        return

    names = [f"{f} {l}" for f in FIRST for l in LAST]
    rng.shuffle(names)
    patients = {n: rng.betavariate(1.2, 5.0) for n in names[:70]}  # hidden no-show propensity
    today = date.today()
    types, weights = zip(*TYPE_WEIGHTS.items())
    username = "seed"

    for offset in range(days, -4, -1):  # oldest first, ending three days ahead
        day = today - timedelta(days=offset)
        if day.weekday() == 6:  # closed Sundays
            continue
        slots = rng.sample([time(h, m) for h in range(8, 18) for m in (0, 30)], rng.randint(8, 14))
        chosen = rng.sample(sorted(patients), len(slots))
        items = []
        for name, slot in zip(chosen, sorted(slots)):
            lead = min(int(rng.expovariate(1 / 9)), 45)
            booked = min(day - timedelta(days=lead), today)
            items.append(AppointmentIn(
                patient_name=name, appointment_date=day, appointment_time=slot,
                appointment_type=AppointmentType(rng.choices(types, weights)[0]), booked_on=booked,
            ))
        created = state.appointments.create_many(items, username)
        if day > today:
            continue  # future days stay scheduled
        for row in created:
            if day == today and rng.random() < 0.4:
                continue  # some of today's visits are still open
            p = patients[row["patient_name"]]
            p += 0.005 * min(row["lead_days"], 30)  # long lead time makes no-shows likelier
            status = Status.NO_SHOW if rng.random() < p else Status.ATTENDED
            state.appointments.reconcile(row["id"], status, username)

    info = state.model.train()
    rescored = state.model.rescore_scheduled()
    total = state.appointments_repo.count()
    print(f"Seeded {total} appointments. Retrained {info.version} "
          f"(AUC {info.metrics['auc']:.3f}); re-scored {rescored} open appointments.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    run(args.days, args.seed)
