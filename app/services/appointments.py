"""Creating, scoring and reconciling appointments."""
from __future__ import annotations

from app.cache import TTLCache
from app.db import AppointmentRepository
from app.errors import ConflictError, NotFoundError
from app.ml.features import features_for_new
from app.ml.model import ModelService
from app.schemas import AppointmentIn, Status, patient_key


class AppointmentService:
    def __init__(self, repo: AppointmentRepository, model: ModelService, cache: TTLCache):
        self.repo = repo
        self.model = model
        self.cache = cache

    def create_many(self, items: list[AppointmentIn], username: str) -> list[dict]:
        """Score and store a batch atomically (all rows are saved or none are)."""
        seen: set[tuple[str, object, object]] = set()
        for it in items:
            slot = (patient_key(it.patient_name), it.appointment_date, it.appointment_time)
            if slot in seen:
                raise ConflictError(
                    f"{it.patient_name} is listed twice for {it.appointment_date} at "
                    f"{it.appointment_time:%H:%M} in this upload"
                )
            seen.add(slot)

        keys = [patient_key(i.patient_name) for i in items]
        history = self.repo.history_for(keys)
        feats = [
            features_for_new(
                appointment_date=i.appointment_date,
                hour=i.appointment_time.hour,
                appointment_type=i.appointment_type.value,
                lead_days=i.lead_days,
                history=history[k],
            )
            for i, k in zip(items, keys)
        ]
        predictions, version = self.model.predict(feats)  # one vectorised call for the whole batch

        rows = [
            {
                "patient_name": i.patient_name,
                "patient_key": k,
                "appointment_date": i.appointment_date.isoformat(),
                "appointment_time": f"{i.appointment_time:%H:%M}",
                "appointment_type": i.appointment_type.value,
                "booked_on": i.effective_booked_on.isoformat(),
                "lead_days": i.lead_days,
                "risk_score": p.risk,
                "risk_level": p.level,
                "predicted_no_show": int(p.flagged),
                "model_version": version,
                "created_by": username,
            }
            for i, k, p in zip(items, keys, predictions)
        ]
        ids = self.repo.insert_many(rows)
        self.cache.invalidate()
        return self.repo.get_many(ids)

    def reconcile(self, appt_id: int, status: Status, username: str) -> dict:
        if not self.repo.update_status(appt_id, status.value, username):
            raise NotFoundError(f"Appointment {appt_id} not found")
        self.cache.invalidate()
        return self.repo.get(appt_id)

    def delete(self, appt_id: int) -> None:
        if not self.repo.delete(appt_id):
            raise NotFoundError(f"Appointment {appt_id} not found")
        self.cache.invalidate()
