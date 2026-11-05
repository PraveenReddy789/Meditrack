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
from dataclasses import replace
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


def run(days: int, seed: int, force: bool = False) -> None:
    rng = random.Random(seed)
    settings = replace(Settings.from_env(), allow_past_appointments=True)
    state = build_state(settings)
    if state.appointments_repo.count() > 0:
        if not force:
            print("Database already has appointments; use --force to overwrite them.")
            return
        with state.db.connect() as conn:
            conn.execute("DELETE FROM appointments")

    names = [f"{f} {l}" for f in FIRST for l in LAST]
    rng.shuffle(names)
    patients = {n: rng.betavariate(1.2, 5.0) for n in names[:70]}  # hidden no-show propensity
    indian_prefixes = [93982, 98451, 97412, 88842, 70221, 91080, 99001, 94480, 98230, 97654, 98110, 98765, 96320, 99450, 98800]
    phones = {n: f"+91 {rng.choice(indian_prefixes)} {rng.randint(10000, 99999)}" for n in patients}
    today = date.today()
    types, weights = zip(*TYPE_WEIGHTS.items())
    username = "seed"

    from datetime import datetime

    valid_times = [time(h, m) for h in range(9, 17) for m in (0, 30)] + [time(17, 0)]

    for offset in range(days, -4, -1):  # oldest first, ending three days ahead
        day = today - timedelta(days=offset)
        if day.weekday() == 6:  # closed Sundays
            continue
        slots = rng.sample(valid_times, min(len(valid_times), rng.randint(8, 14)))
        chosen = rng.sample(sorted(patients), len(slots))
        items = []
        for name, slot in zip(chosen, sorted(slots)):
            lead = min(int(rng.expovariate(1 / 9)), 45)
            booked = min(day - timedelta(days=lead), today)
            items.append(AppointmentIn(
                patient_name=name, patient_phone=phones[name], appointment_date=day, appointment_time=slot,
                appointment_type=AppointmentType(rng.choices(types, weights)[0]), booked_on=booked,
            ))
        created = state.appointments.create_many(items, username)
        if day > today:
            continue  # future days stay scheduled

        now_time = datetime.now().time()
        for row in created:
            appt_time = time.fromisoformat(row["appointment_time"])
            if day == today:
                if appt_time > now_time:
                    continue  # upcoming slots today remain open/scheduled for live demo
                p = patients[row["patient_name"]]
                status = Status.NO_SHOW if rng.random() < p else Status.ATTENDED
                state.appointments.reconcile(row["id"], status, username)
            else:
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
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--force", action="store_true", help="Overwrite existing appointments")
    args = ap.parse_args()
    run(args.days, args.seed, args.force)
