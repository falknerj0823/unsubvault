import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from app.core import app_settings, audit
from app.core.security import (COOKIE_NAME, MIN_PASSWORD_LEN, SESSION_TTL, check_admin_password,
                               make_session_token, require_auth, set_admin_password, sign_out_everywhere)

router = APIRouter()

MAX_FAILURES, WINDOW = 5, 300
_failures: dict[str, list[float]] = {}

class LoginRequest(BaseModel):
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

def _ip(request: Request) -> str:
    return audit.client_ip(request) or "unknown"

def _check_rate(ip: str) -> list[float]:
    recent = [t for t in _failures.get(ip, []) if time.time() - t < WINDOW]
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many failed attempts, try again later")
    return recent

def _set_cookie(response: Response):
    response.set_cookie(COOKIE_NAME, make_session_token(), max_age=SESSION_TTL,
                        httponly=True, samesite="lax", path="/",
                        secure=app_settings.get("frontend_url").startswith("https://"))

@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    ip = _ip(request)
    try:
        recent = _check_rate(ip)
    except HTTPException:
        audit.record("login_blocked", success=False, request=request, actor="anonymous", detail={"reason": "too many failed attempts"})
        raise
    if not check_admin_password(body.password):
        _failures[ip] = recent + [time.time()]
        audit.record("login_failed", success=False, request=request, actor="anonymous", detail={"failures_in_window": len(recent) + 1})
        raise HTTPException(status_code=401, detail="Wrong password")
    _failures.pop(ip, None)
    _set_cookie(response)
    audit.record("login", request=request)
    return {"ok": True}

@router.post("/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    audit.record("logout", request=request)
    return {"ok": True}

@router.post("/change-password", dependencies=[Depends(require_auth)])
def change_password(body: ChangePasswordRequest, request: Request, response: Response):
    ip = _ip(request)
    recent = _check_rate(ip)
    if not check_admin_password(body.current_password):
        _failures[ip] = recent + [time.time()]
        audit.record("password_change_failed", success=False, request=request, detail={"reason": "current password wrong"})
        raise HTTPException(status_code=400, detail="Current password is wrong")
    if len(body.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"New password must be at least {MIN_PASSWORD_LEN} characters")
    set_admin_password(body.new_password)
    audit.record("password_changed", request=request, detail={"other_sessions_signed_out": True})
    _set_cookie(response)  # keep this browser signed in; all other sessions are now invalid
    return {"ok": True}

@router.post("/logout-all", dependencies=[Depends(require_auth)])
def logout_all(request: Request, response: Response):
    """Invalidate every session, including this one and any copied cookie."""
    sign_out_everywhere()
    response.delete_cookie(COOKIE_NAME, path="/")
    audit.record("logout_everywhere", request=request)
    return {"ok": True}

@router.get("/me", dependencies=[Depends(require_auth)])
def me():
    return {"authenticated": True}
