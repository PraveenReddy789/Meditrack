"""Request/response models and input validation rules."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CLINIC_OPEN = time(7, 0)
CLINIC_CLOSE = time(20, 0)  # last bookable slot is 19:59
MAX_PAST_DAYS = 365 * 3
MAX_FUTURE_DAYS = 365


class AppointmentType(str, Enum):
    CHECKUP = "checkup"
    FOLLOW_UP = "follow_up"
    SPECIALIST = "specialist"
    VACCINATION = "vaccination"
    LAB_TEST = "lab_test"


class Status(str, Enum):
    SCHEDULED = "scheduled"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


def clean_name(value: str) -> str:
    """Collapse whitespace; the display form of a patient name."""
    return " ".join(value.split())


def patient_key(value: str) -> str:
    """Case/whitespace-insensitive identity used to link a patient's history."""
    return clean_name(value).casefold()


class AppointmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_name: str = Field(min_length=1, max_length=100)
    appointment_date: date
    appointment_time: time
    appointment_type: AppointmentType = AppointmentType.CHECKUP
    booked_on: date | None = None

    @field_validator("patient_name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = clean_name(v)
        if len(v) < 2:
            raise ValueError("patient name must be at least 2 characters")
        if not all(ch.isalpha() or ch in " .'’-" for ch in v):
            raise ValueError("patient name may contain only letters, spaces, . ' and -")
        return v

    @field_validator("appointment_time")
    @classmethod
    def _valid_time(cls, v: time) -> time:
        if v.tzinfo is not None:
            raise ValueError("appointment time must not include a timezone")
        v = v.replace(second=0, microsecond=0)
        if not (CLINIC_OPEN <= v < CLINIC_CLOSE):
            raise ValueError(
                f"appointment time must be between {CLINIC_OPEN:%H:%M} and {CLINIC_CLOSE:%H:%M}"
            )
        return v

    @model_validator(mode="after")
    def _valid_dates(self) -> "AppointmentIn":
        today = date.today()
        if self.appointment_date < today - timedelta(days=MAX_PAST_DAYS):
            raise ValueError("appointment date is too far in the past")
        if self.appointment_date > today + timedelta(days=MAX_FUTURE_DAYS):
            raise ValueError("appointment date is more than a year ahead")
        if self.booked_on is not None and self.booked_on > self.appointment_date:
            raise ValueError("booked_on cannot be after the appointment date")
        return self

    @property
    def effective_booked_on(self) -> date:
        """Booking date, defaulting to today (or the visit day for historical entries)."""
        if self.booked_on is not None:
            return self.booked_on
        return min(date.today(), self.appointment_date)

    @property
    def lead_days(self) -> int:
        return (self.appointment_date - self.effective_booked_on).days


class BulkAppointmentsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appointments: list[AppointmentIn] = Field(min_length=1)


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AppointmentOut(BaseModel):
    id: int
    patient_name: str
    appointment_date: date
    appointment_time: str
    appointment_type: AppointmentType
    booked_on: date
    lead_days: int
    status: Status
    risk_score: float | None
    risk_level: str | None
    predicted_no_show: bool
    model_version: str | None
    created_by: str
    reconciled_by: str | None
    reconciled_at: datetime | None


class UserOut(BaseModel):
    username: str
    role: str
    permissions: list[str]
