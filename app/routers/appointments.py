from datetime import date

from fastapi import APIRouter, Depends, Path, Query, Response

from app.deps import AppState, get_state, require
from app.errors import ValidationFailedError
from app.schemas import AppointmentIn, AppointmentOut, BulkAppointmentsIn, Status, StatusUpdate
from app.security import APPOINTMENTS_DELETE, APPOINTMENTS_READ, APPOINTMENTS_WRITE, AuthUser

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentOut, status_code=201)
def create_appointment(
    body: AppointmentIn,
    user: AuthUser = Depends(require(APPOINTMENTS_WRITE)),
    state: AppState = Depends(get_state),
):
    return state.appointments.create_many([body], user.username)[0]


@router.post("/bulk", response_model=list[AppointmentOut], status_code=201)
def create_appointments_bulk(
    body: BulkAppointmentsIn,
    user: AuthUser = Depends(require(APPOINTMENTS_WRITE)),
    state: AppState = Depends(get_state),
):
    limit = state.settings.max_bulk_rows
    if len(body.appointments) > limit:
        raise ValidationFailedError(f"At most {limit} appointments can be uploaded at once.")
    return state.appointments.create_many(body.appointments, user.username)


@router.get("")
def list_appointments(
    day: date | None = Query(None, alias="date", description="Single day (shortcut for start=end=date)"),
    start: date | None = None,
    end: date | None = None,
    status: Status | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: AuthUser = Depends(require(APPOINTMENTS_READ)),
    state: AppState = Depends(get_state),
):
    if day:
        start = end = day
    if start and end and start > end:
        raise ValidationFailedError("start must not be after end")
    s, e = (start.isoformat() if start else None), (end.isoformat() if end else None)
    repo = state.appointments_repo
    items = repo.list(start=s, end=e, status=status.value if status else None, limit=limit, offset=offset)
    total = repo.count(start=s, end=e, status=status.value if status else None)
    return {"items": [AppointmentOut.model_validate(_public(r)) for r in items], "total": total}


@router.patch("/{appt_id}", response_model=AppointmentOut)
def reconcile_appointment(
    body: StatusUpdate,
    appt_id: int = Path(ge=1),
    user: AuthUser = Depends(require(APPOINTMENTS_WRITE)),
    state: AppState = Depends(get_state),
):
    return state.appointments.reconcile(appt_id, body.status, user.username)


@router.delete("/{appt_id}", status_code=204)
def delete_appointment(
    appt_id: int = Path(ge=1),
    _: AuthUser = Depends(require(APPOINTMENTS_DELETE)),
    state: AppState = Depends(get_state),
):
    state.appointments.delete(appt_id)
    return Response(status_code=204)


def _public(row: dict) -> dict:
    return {**row, "predicted_no_show": bool(row["predicted_no_show"])}
