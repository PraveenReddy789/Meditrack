from datetime import date

import numpy as np
import pytest

from app.config import Settings
from app.db import AppointmentRepository, Database
from app.ml.features import (
    FEATURE_NAMES, AppointmentFeatures, encode, features_for_new, prior_counts, smoothed_rate,
    training_set_from_rows,
)
from app.ml.model import FALLBACK_VERSION, ModelService, risk_level, train_model
from app.ml.synthetic import generate


def feat(**kw):
    base = dict(lead_days=7, hour=10, weekday=1, appointment_type="checkup", prior_visits=3, prior_no_shows=0)
    base.update(kw)
    return AppointmentFeatures(**base)


# ---- features --------------------------------------------------------------
def test_encode_shape_and_one_hots():
    X = encode([feat(weekday=2, appointment_type="specialist")])
    assert X.shape == (1, len(FEATURE_NAMES))
    names = dict(zip(FEATURE_NAMES, X[0]))
    assert names["weekday_2"] == 1.0 and sum(names[f"weekday_{d}"] for d in range(7)) == 1.0
    assert names["type_specialist"] == 1.0 and names["type_checkup"] == 0.0
    assert names["first_visit"] == 0.0


def test_encode_clips_and_never_lets_no_shows_exceed_visits():
    names = dict(zip(FEATURE_NAMES, encode([feat(lead_days=500, prior_visits=2, prior_no_shows=9)])[0]))
    assert names["lead_days"] == 60
    assert names["prior_no_shows"] == 2


def test_encode_rejects_unknown_type():
    with pytest.raises(ValueError):
        encode([feat(appointment_type="surgery")])


def test_first_visit_flag_and_smoothing():
    names = dict(zip(FEATURE_NAMES, encode([feat(prior_visits=0, prior_no_shows=0)])[0]))
    assert names["first_visit"] == 1.0
    assert smoothed_rate(0, 0) == pytest.approx(0.2)
    assert smoothed_rate(10, 10) > smoothed_rate(1, 1) > 0.2  # more evidence moves further from the base rate


def test_prior_counts_are_strictly_before_the_visit_date():
    hist = [("2026-01-01", "attended"), ("2026-01-05", "no_show"), ("2026-01-10", "no_show")]
    assert prior_counts(hist, "2026-01-05") == (1, 0)
    assert prior_counts(hist, "2026-01-11") == (3, 2)
    assert prior_counts([], "2026-01-11") == (0, 0)


def test_features_for_new_uses_weekday_and_history():
    f = features_for_new(
        appointment_date=date(2026, 3, 2), hour=9, appointment_type="lab_test", lead_days=4,
        history=[("2026-02-01", "no_show")],
    )
    assert (f.weekday, f.prior_visits, f.prior_no_shows) == (0, 1, 1)


def row(key, day, status, time="09:00", lead=3, typ="checkup"):
    return dict(patient_key=key, appointment_date=day, appointment_time=time, appointment_type=typ,
                lead_days=lead, status=status)


def test_training_set_has_no_same_day_or_future_leakage():
    rows = [
        row("a", "2026-01-01", "no_show"),
        row("a", "2026-01-01", "attended", time="15:00"),  # same day: must not see the morning outcome
        row("a", "2026-01-08", "attended"),
        row("b", "2026-01-08", "attended"),
    ]
    feats, labels = training_set_from_rows(rows)
    assert [f.prior_visits for f in feats] == [0, 0, 2, 0]
    assert [f.prior_no_shows for f in feats] == [0, 0, 1, 0]
    assert labels.tolist() == [1, 0, 0, 0]


# ---- synthetic data --------------------------------------------------------
def test_synthetic_generation_is_deterministic_and_plausible():
    f1, y1 = generate(1000, 5)
    f2, y2 = generate(1000, 5)
    assert f1 == f2 and (y1 == y2).all()
    assert 0.12 < y1.mean() < 0.32
    assert all(0 <= f.prior_no_shows <= f.prior_visits for f in f1)


# ---- training --------------------------------------------------------------
@pytest.fixture(scope="module")
def trained_logistic():
    feats, y = generate(3000, 42)
    return train_model("logistic", feats, y, np.ones(len(y)), 42, 3000, 0)


def test_trained_model_beats_chance_and_reports_metrics(trained_logistic):
    info = trained_logistic.info
    assert info.metrics["auc"] > 0.60
    assert 0.0 < info.threshold < 1.0
    assert {"auc", "brier", "accuracy", "precision", "recall", "f1"} <= info.metrics.keys()
    assert info.single_predict_ms > 0 and info.train_seconds > 0
    assert info.top_features  # logistic exposes its drivers


def test_gbm_trains_and_scores():
    feats, y = generate(1500, 1)
    m = train_model("gbm", feats, y, np.ones(len(y)), 1, 1500, 0)
    assert m.info.metrics["auc"] > 0.55
    assert m.info.top_features == []


def test_unknown_model_kind_is_rejected():
    feats, y = generate(600, 1)
    with pytest.raises(ValueError):
        train_model("forest", feats, y, np.ones(len(y)), 1, 600, 0)


def test_settings_validate_model_kind():
    with pytest.raises(ValueError):
        Settings(model_kind="forest")


def test_risk_level_boundaries():
    assert risk_level(0.40, 0.30) == "high"
    assert risk_level(0.30, 0.30) == "high"
    assert risk_level(0.15, 0.30) == "medium"
    assert risk_level(0.14, 0.30) == "low"


# ---- service ---------------------------------------------------------------
@pytest.fixture()
def service(tmp_path):
    db = Database(tmp_path / "m.db")
    db.init_schema()
    repo = AppointmentRepository(db)
    svc = ModelService(Settings(synthetic_rows=1500), repo)
    svc.train()
    return svc, repo


def test_predictions_are_probabilities_and_batch_matches_single(service):
    svc, _ = service
    feats = [feat(lead_days=d, prior_no_shows=n, prior_visits=4) for d in (0, 10, 40) for n in (0, 2, 4)]
    batch, version = svc.predict(feats)
    assert all(0.0 <= p.risk <= 1.0 for p in batch)
    singles = [svc.predict([f])[0][0] for f in feats]
    assert [p.risk for p in batch] == [p.risk for p in singles]
    assert version == svc.info.version


def test_model_responds_sensibly_to_inputs(service):
    svc, _ = service
    (clean,), _ = svc.predict([feat(prior_visits=6, prior_no_shows=0)])
    (repeat,), _ = svc.predict([feat(prior_visits=6, prior_no_shows=5)])
    assert repeat.risk > clean.risk
    (soon,), _ = svc.predict([feat(lead_days=1)])
    (far,), _ = svc.predict([feat(lead_days=45)])
    assert far.risk > soon.risk


def test_empty_batch_is_fine(service):
    svc, _ = service
    assert svc.predict([])[0] == []


def test_prediction_falls_back_to_heuristic_instead_of_failing(service, monkeypatch):
    svc, _ = service

    def boom(_X):
        raise RuntimeError("corrupt model")

    monkeypatch.setattr(svc._model.pipeline, "predict_proba", boom)
    preds, version = svc.predict([feat(prior_visits=4, prior_no_shows=4), feat(prior_visits=4, prior_no_shows=0)])
    assert version == FALLBACK_VERSION
    assert preds[0].risk > preds[1].risk and 0 <= preds[1].risk <= 1


def test_untrained_service_still_answers(tmp_path):
    db = Database(tmp_path / "u.db")
    db.init_schema()
    svc = ModelService(Settings(synthetic_rows=1500), AppointmentRepository(db))
    preds, version = svc.predict([feat()])
    assert version == FALLBACK_VERSION and len(preds) == 1


def db_row(name, day, status, **kw):
    base = dict(
        patient_name=name.title(), patient_key=name, appointment_date=day, appointment_time="09:00",
        appointment_type="checkup", booked_on=day, lead_days=0, risk_score=0.2, risk_level="low",
        predicted_no_show=0, model_version="v", created_by="staff",
    )
    base.update(kw)
    return base, status


def test_retrain_blends_in_real_reconciled_rows(service):
    svc, repo = service
    assert svc.info.n_real == 0
    items = [db_row(f"patient {i}", f"2026-02-{i % 27 + 1:02d}", "no_show" if i % 3 == 0 else "attended")
             for i in range(60)]
    ids = repo.insert_many([r for r, _ in items])
    for appt_id, (_, status) in zip(ids, items):
        repo.update_status(appt_id, status, "staff")
    info = svc.train()
    assert info.n_real == 60 and info.n_synthetic == 1500


def test_rescore_updates_scheduled_appointments(service):
    svc, repo = service
    (r, _), = [db_row("new person", "2026-12-01", "scheduled", model_version="old", risk_score=0.99)]
    (appt_id,) = repo.insert_many([r])
    assert svc.rescore_scheduled() == 1
    got = repo.get(appt_id)
    assert got["model_version"] == svc.info.version and got["risk_score"] != 0.99
