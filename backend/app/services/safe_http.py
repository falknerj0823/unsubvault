"""Outbound requests to URLs taken from untrusted email headers.

Guards: https only, port 443 only, no credentials in the URL, every resolved address must be public,
the connection is pinned to the validated address (no DNS-rebinding gap), redirects are followed by hand
and re-validated at every hop, no cookies or proxies, short timeout, the body is never downloaded."""
import asyncio, ipaddress, socket
from urllib.parse import urljoin, urlsplit
import httpx

ALLOWED_PORT = 443
TOTAL_DEADLINE = 45  # seconds for a whole fetch including redirects; the per-request timeout alone allows slow-drip stalls
_BLOCKED_NETS = [ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")]  # NAT64, 6to4, Teredo
MAX_REDIRECTS = 5
TIMEOUT = 15
USER_AGENT = "UnsubVault/0.1 (self-hosted unsubscribe)"

class UnsafeURL(ValueError):
    """The URL (or a redirect target) must not be requested. The message is safe to show the user."""

def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast and not any(addr in n for n in _BLOCKED_NETS)

def validate_url(url: str) -> tuple[str, int, list[str]]:
    """Returns (host, port, public_ips) or raises UnsafeURL. Blocking: does a DNS lookup."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() != "https":
        raise UnsafeURL("only https links are allowed")
    if parts.username or parts.password:
        raise UnsafeURL("links with embedded credentials are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeURL("link has no host")
    try:
        port = parts.port or ALLOWED_PORT
    except ValueError:
        raise UnsafeURL("link has an invalid port")
    if port != ALLOWED_PORT:
        raise UnsafeURL(f"port {port} is not allowed")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURL(f"could not resolve {host}")
    ips = sorted({i[4][0] for i in infos})
    if not ips or not all(_is_public(ip) for ip in ips):
        raise UnsafeURL(f"{host} points at a non-public address")
    return host, port, ips

async def _fetch(method: str, url: str, form: dict | None, max_body: int) -> tuple[int, str, bytes]:
    """Shared by the helpers below. max_body=0 never reads the body; otherwise reads at most max_body bytes
    and raises UnsafeURL if the response is larger."""
    current, verb, body = url, method.upper(), form
    for _ in range(MAX_REDIRECTS + 1):
        host, port, ips = await asyncio.to_thread(validate_url, current)
        ip = ips[0]
        netloc = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
        target = urlsplit(current)._replace(netloc=netloc).geturl()
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as client:
            req = client.build_request(verb, target, data=body, headers={"Host": host, "User-Agent": USER_AGENT},
                                       extensions={"sni_hostname": host})
            resp = await client.send(req, stream=True)
            status, location = resp.status_code, resp.headers.get("location")
            data = b""
            try:
                if max_body and not (status in (301, 302, 303, 307, 308) and location):
                    async for chunk in resp.aiter_bytes():
                        data += chunk
                        if len(data) > max_body:
                            raise UnsafeURL("the response is larger than allowed")
            finally:
                await resp.aclose()
        if status in (301, 302, 303, 307, 308) and location:
            current = urljoin(current, location)
            if status in (301, 302, 303):
                verb, body = "GET", None
            continue
        return status, current, data
    raise UnsafeURL("too many redirects")

async def _with_deadline(coro):
    try:
        return await asyncio.wait_for(coro, TOTAL_DEADLINE)
    except asyncio.TimeoutError:
        raise UnsafeURL("the site took too long to answer")

async def safe_request(method: str, url: str, form: dict | None = None) -> tuple[int, str]:
    """Returns (final_status, final_url). The body is never downloaded."""
    status, final, _ = await _with_deadline(_fetch(method, url, form, 0))
    return status, final

async def safe_get_bytes(url: str, max_bytes: int = 5_000_000) -> tuple[int, bytes]:
    """GET with a hard size cap. Returns (status, body)."""
    status, _, data = await _with_deadline(_fetch("GET", url, None, max_bytes))
    return status, data
