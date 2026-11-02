from datetime import date, time, timedelta

import pytest
from pydantic import ValidationError

from app.schemas import AppointmentIn, patient_key


def make(**overrides):
    base = {
        "patient_name": "Asha Rao",
        "appointment_date": date.today().isoformat(),
        "appointment_time": "09:30",
    }
    base.update(overrides)
    return AppointmentIn(**base)


def test_valid_appointment_normalizes_name_and_time():
    a = make(patient_name="  Asha    Rao ", appointment_time="09:30:45")
    assert a.patient_name == "Asha Rao"
    assert a.appointment_time == time(9, 30)


@pytest.mark.parametrize("name", ["", "A", "Robert'); DROP TABLE x;--", "<script>alert(1)</script>", "R2D2", "Bob\x00"])
def test_rejects_bad_names(name):
    with pytest.raises(ValidationError):
        make(patient_name=name)


@pytest.mark.parametrize("name", ["Mary-Jane O'Neil", "José Álvarez", "Dr. Priya Nair", "Ananya Reddy"])
def test_accepts_realistic_names(name):
    assert make(patient_name=name).patient_name == name


@pytest.mark.parametrize("t", ["06:59", "20:00", "23:30", "00:00"])
def test_rejects_times_outside_clinic_hours(t):
    with pytest.raises(ValidationError):
        make(appointment_time=t)


def test_rejects_timezone_aware_time():
    with pytest.raises(ValidationError):
        make(appointment_time="09:30+05:30")


def test_rejects_unparseable_time_and_date():
    with pytest.raises(ValidationError):
        make(appointment_time="half past nine")
    with pytest.raises(ValidationError):
        make(appointment_date="2026-13-45")


def test_rejects_dates_out_of_range():
    with pytest.raises(ValidationError):
        make(appointment_date=(date.today() + timedelta(days=400)).isoformat())
    with pytest.raises(ValidationError):
        make(appointment_date=(date.today() - timedelta(days=365 * 4)).isoformat())


def test_booked_on_cannot_be_after_visit():
    with pytest.raises(ValidationError):
        make(booked_on=(date.today() + timedelta(days=1)).isoformat())


def test_lead_days_calculation():
    visit = date.today() + timedelta(days=10)
    assert make(appointment_date=visit.isoformat()).lead_days == 10
    booked = (date.today() - timedelta(days=5)).isoformat()
    assert make(appointment_date=visit.isoformat(), booked_on=booked).lead_days == 15
    # historical entries without booked_on do not produce negative lead time
    past = (date.today() - timedelta(days=30)).isoformat()
    assert make(appointment_date=past).lead_days == 0


def test_unknown_fields_and_types_are_rejected():
    with pytest.raises(ValidationError):
        make(status="attended")
    with pytest.raises(ValidationError):
        make(appointment_type="surgery")


def test_patient_key_is_case_and_space_insensitive():
    assert patient_key("  ASHA   rao") == patient_key("asha rao")
