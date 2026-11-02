from fastapi import APIRouter, Depends

from app.deps import AppState, get_state, require
from app.errors import ConflictError
from app.security import MODEL_TRAIN, REPORTS_READ, AuthUser

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("")
def model_info(_: AuthUser = Depends(require(REPORTS_READ)), state: AppState = Depends(get_state)):
    return state.model.info.as_dict()


@router.post("/retrain")
def retrain(_: AuthUser = Depends(require(MODEL_TRAIN)), state: AppState = Depends(get_state)):
    """Retrain on synthetic baseline + all reconciled appointments, then re-score upcoming ones."""
    if not state.retrain_lock.acquire(blocking=False):
        raise ConflictError("A retrain is already running.")
    try:
        info = state.model.train()
        rescored = state.model.rescore_scheduled()
        state.cache.invalidate()
    finally:
        state.retrain_lock.release()
    return {**info.as_dict(), "rescored_appointments": rescored}
