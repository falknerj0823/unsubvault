import time
import msal
from app.core import app_settings

# MSAL adds openid, profile and offline_access itself and rejects them if listed here.
SCOPES = ["https://outlook.office.com/IMAP.AccessAsUser.All"]
IMAP_HOST = "outlook.office365.com"

FLOW_TTL = 600
_flows: dict[str, tuple[float, dict]] = {}  # state -> (created_at, msal flow); single backend process

def redirect_uri() -> str:
    return f"{app_settings.get('frontend_url').rstrip('/')}/api/auth/microsoft/callback"

def is_configured() -> bool:
    return bool(app_settings.get("microsoft_client_id") and app_settings.get("microsoft_client_secret"))

def _app():
    return msal.ConfidentialClientApplication(
        app_settings.get("microsoft_client_id"),
        authority=f"https://login.microsoftonline.com/{app_settings.get('microsoft_tenant')}",
        client_credential=app_settings.get("microsoft_client_secret"),
    )

def start_flow() -> str:
    """Begin an authorization-code flow (state + PKCE) and return the Microsoft sign-in URL."""
    now = time.time()
    for state in [s for s, (t, _) in _flows.items() if now - t > FLOW_TTL]:
        _flows.pop(state, None)
    flow = _app().initiate_auth_code_flow(SCOPES, redirect_uri=redirect_uri())
    if "auth_uri" not in flow:
        raise ValueError(flow.get("error_description") or flow.get("error") or "Could not start Microsoft sign-in")
    _flows[flow["state"]] = (now, flow)
    return flow["auth_uri"]

def finish_flow(params: dict) -> dict:
    """Validate state and exchange the code. Raises ValueError for an unknown/expired/replayed state."""
    entry = _flows.pop(params.get("state", ""), None)
    if not entry or time.time() - entry[0] > FLOW_TTL:
        raise ValueError("invalid_state")
    return _app().acquire_token_by_auth_code_flow(entry[1], params, scopes=SCOPES)

def refresh_token(refresh_token: str) -> dict:
    return _app().acquire_token_by_refresh_token(refresh_token, SCOPES)
