import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core import app_settings, audit
from app.core.crypto import encrypt
from app.core.database import get_db
from app.models.account import Account, ProviderType
from app.services import oauth_microsoft

router = APIRouter()
log = logging.getLogger(__name__)

def _back(**query) -> RedirectResponse:
    return RedirectResponse(f"{app_settings.get('frontend_url').rstrip('/')}/accounts?{urlencode(query)}")

@router.get("/microsoft/login")
def microsoft_login(request: Request):
    if not oauth_microsoft.is_configured():
        audit.record("microsoft_signin_failed", success=False, request=request, detail={"error": "not configured"})
        return _back(error="microsoft_not_configured")
    try:
        url = oauth_microsoft.start_flow()
        audit.record("microsoft_signin_started", request=request)
        return RedirectResponse(url)
    except Exception:
        log.exception("Microsoft sign-in could not start")
        return _back(error="microsoft_start_failed")

@router.get("/microsoft/callback")
def microsoft_callback(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    if "error" in params:  # user cancelled or Microsoft refused; only the short code goes back to the UI
        audit.record("microsoft_signin_failed", success=False, request=request, detail={"error": params["error"][:60]})
        return _back(error=params["error"][:60])
    try:
        result = oauth_microsoft.finish_flow(params)
    except ValueError:
        audit.record("microsoft_signin_failed", success=False, request=request, detail={"error": "invalid_state"})
        return _back(error="invalid_state")
    except Exception:
        log.exception("Microsoft token exchange failed")
        audit.record("microsoft_signin_failed", success=False, request=request, detail={"error": "token_exchange_failed"})
        return _back(error="token_exchange_failed")
    if "access_token" not in result:
        # error_description starts with the AADSTS code; later lines hold trace/correlation ids, so keep line one only
        detail = str(result.get("error_description", "")).split("\n")[0][:200]
        log.warning("Microsoft sign-in returned no token: %s | %s", result.get("error"), detail)
        audit.record("microsoft_signin_failed", success=False, request=request, detail={"error": result.get("error"), "description": detail})
        return _back(error=str(result.get("error", "no_token"))[:60])
    claims = result.get("id_token_claims") or {}
    address = claims.get("preferred_username") or claims.get("email")
    if not address:
        audit.record("microsoft_signin_failed", success=False, request=request, detail={"error": "no_email_in_token"})
        return _back(error="no_email_in_token")
    acct = (db.query(Account).filter(Account.provider_type == ProviderType.microsoft,
                                     Account.email_address == address).first()
            or Account(label=address, provider_type=ProviderType.microsoft, email_address=address))
    acct.imap_host, acct.imap_port, acct.imap_username = oauth_microsoft.IMAP_HOST, 993, address
    acct.access_token = encrypt(result["access_token"])
    if result.get("refresh_token"):
        acct.refresh_token = encrypt(result["refresh_token"])
    acct.token_expires_at = datetime.utcnow() + timedelta(seconds=int(result.get("expires_in", 3600)))
    is_new = acct.id is None
    db.add(acct); db.commit()
    audit.record("account_connected" if is_new else "account_reconnected", request=request, detail={"provider": "microsoft", "email": address})
    return _back(connected=address)

@router.get("/microsoft/redirect-uri")
def microsoft_redirect_uri():
    """The exact URI to register in the Azure app registration."""
    return {"redirect_uri": oauth_microsoft.redirect_uri(), "configured": oauth_microsoft.is_configured()}
