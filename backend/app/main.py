from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, accounts, scan, emails, settings, session, audit as audit_api, unsubscribe, spam, privacy
from app.core import app_settings, audit
from app.core.config import settings as app_config
from app.services.scanner import recover_interrupted
from app.core.security import require_auth, validate_startup_config

@asynccontextmanager
async def lifespan(_):
    validate_startup_config()
    audit.prune()
    interrupted = recover_interrupted()
    audit.record("app_started", actor="system", detail={"interrupted_scans_marked_failed": interrupted["scans"], "interrupted_unsubscribe_jobs_marked_failed": interrupted["unsubscribe_jobs"]})
    import asyncio
    from app.api.privacy import _CATALOG
    from app.services.linkcheck import weekly_loop
    task = asyncio.create_task(weekly_loop(_CATALOG["brokers"]))
    yield
    task.cancel()

app = FastAPI(title="UnsubVault", lifespan=lifespan)
# The UI is served from the same origin through nginx, so cross-origin access is only needed for the configured frontend URL.
app.add_middleware(CORSMiddleware, allow_origins=[app_config.frontend_url] if app_config.frontend_url else [],
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["content-type"])
@app.middleware("http")
async def block_cross_site_writes(request: Request, call_next):
    """Defence in depth on top of SameSite cookies: a browser request that changes state must come from this app's own origin."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin:
            allowed = {urlsplit(app_settings.get("frontend_url")).netloc, request.headers.get("host", "")}
            if urlsplit(origin).netloc not in allowed:
                return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        elif request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)

app.include_router(session.router, prefix="/api/session", tags=["session"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"], dependencies=[Depends(require_auth)])
app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(require_auth)])
app.include_router(scan.router, prefix="/api/scan", tags=["scan"], dependencies=[Depends(require_auth)])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"], dependencies=[Depends(require_auth)])
app.include_router(unsubscribe.router, prefix="/api/unsubscribe", tags=["unsubscribe"], dependencies=[Depends(require_auth)])
app.include_router(spam.router, prefix="/api/spam", tags=["spam"], dependencies=[Depends(require_auth)])
app.include_router(privacy.router, prefix="/api/privacy", tags=["privacy"], dependencies=[Depends(require_auth)])
app.include_router(audit_api.router, prefix="/api/audit", tags=["audit"], dependencies=[Depends(require_auth)])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

@app.get("/api/health")
def health():
    return {"status": "ok"}
