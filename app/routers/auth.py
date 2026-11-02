from fastapi import APIRouter, Depends, Request, Response

from app.deps import SESSION_COOKIE, AppState, current_user, get_state
from app.schemas import LoginIn, UserOut
from app.security import AuthUser

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: AuthUser) -> UserOut:
    return UserOut(username=user.username, role=user.role, permissions=sorted(user.permissions))


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, state: AppState = Depends(get_state)):
    client = request.client.host if request.client else "unknown"
    token, user = state.auth.login(body.username, body.password, client)
    s = state.settings
    # HttpOnly keeps the token away from page scripts; SameSite=Strict blocks cross-site requests (CSRF).
    response.set_cookie(
        SESSION_COOKIE, token, max_age=s.session_ttl_minutes * 60, httponly=True,
        samesite="strict", secure=s.cookie_secure, path="/",
    )
    return _user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, state: AppState = Depends(get_state)):
    state.auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: AuthUser = Depends(current_user)):
    return _user_out(user)
