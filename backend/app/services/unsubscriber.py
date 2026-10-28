"""Unsubscribe from one sender using its List-Unsubscribe header.

Outcomes (UnsubscribeResult.status):
  confirmed        RFC 8058 one-click POST accepted (2xx)
  sent_unverified  plain web link requested (2xx); it may only have opened a confirmation page
  manual           nothing we can safely automate (mailto only, http only, no link); the user must act
  failed           we tried and the request failed or was refused
  dry_run          dry-run: nothing was sent, `method` says what would have happened"""
import re
from dataclasses import dataclass
from typing import Optional
import httpx
from app.services.safe_http import UnsafeURL, safe_request

@dataclass
class UnsubscribeResult:
    status: str
    method: str
    url: Optional[str] = None
    error: Optional[str] = None

def parse_header(header: str) -> tuple[list[str], Optional[str]]:
    """All <...> targets: (web urls, first mailto)."""
    urls, mailto = [], None
    for part in re.findall(r"<([^>]+)>", header or ""):
        part = part.strip()
        if part.lower().startswith(("http://", "https://")):
            urls.append(part)
        elif part.lower().startswith("mailto:") and not mailto:
            mailto = part
    return urls, mailto

def pick_target(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(https_url, mailto). Plain http links are never requested."""
    urls, mailto = parse_header(header or "")
    return next((u for u in urls if u.lower().startswith("https://")), None), mailto

async def unsubscribe(url: Optional[str], mailto: Optional[str], one_click: bool, dry_run: bool = True) -> UnsubscribeResult:
    if not url:
        if mailto:
            return UnsubscribeResult("manual", "mailto", mailto, "Only a mailto: address is offered; send it from your own mail app.")
        return UnsubscribeResult("manual", "none", None, "No usable https unsubscribe link in the email.")
    method = "rfc8058_post" if one_click else "http_get"
    if dry_run:
        return UnsubscribeResult("dry_run", method, url)
    try:
        status, final = await safe_request("POST" if one_click else "GET", url,
                                           {"List-Unsubscribe": "One-Click"} if one_click else None)
    except UnsafeURL as e:
        return UnsubscribeResult("failed", method, url, f"Blocked for safety: {e}")
    except httpx.HTTPError as e:
        return UnsubscribeResult("failed", method, url, f"Request failed: {type(e).__name__}")
    if 200 <= status < 300:
        return UnsubscribeResult("confirmed" if one_click else "sent_unverified", method, url)
    return UnsubscribeResult("failed", method, url, f"The sender answered HTTP {status}.")
