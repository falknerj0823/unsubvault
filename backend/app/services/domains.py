"""Small helpers for comparing sender addresses by company (registrable domain)."""
_TWO_LEVEL_TLDS = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "com.br", "com.mx", "co.in", "co.za"}

def domain_of(address: str | None) -> str:
    return (address or "").rsplit("@", 1)[-1].strip().strip(".").lower()

def root_domain(address_or_domain: str | None) -> str:
    """eg.shop.example.com -> example.com; mail.foo.co.uk -> foo.co.uk. Not a full public-suffix list, which is fine here."""
    d = domain_of(address_or_domain)
    parts = d.split(".")
    if len(parts) <= 2:
        return d
    return ".".join(parts[-3:]) if ".".join(parts[-2:]) in _TWO_LEVEL_TLDS else ".".join(parts[-2:])

def minimized_sender(address: str | None) -> str:
    """For mail we never offer for unsubscribe (receipts, personal) keep only the company domain."""
    return "@" + domain_of(address)

_GENERIC_WORDS = {"the", "team", "inc", "llc", "corp", "company", "news", "newsletter", "updates", "update", "support", "service", "services",
                  "customer", "care", "offers", "offer", "deals", "rewards", "reward", "mail", "email", "info", "noreply", "reply", "alerts",
                  "alert", "notifications", "online", "official", "store", "shop", "club", "member", "members", "account", "accounts", "free", "from", "your",
                  "billing", "payment", "payments", "security", "orders", "order", "receipts", "invoice", "invoices", "marketing", "promotions", "deals"}

def brand_tokens(display_name: str | None) -> list[str]:
    """The distinctive words of a sender name ('Orbit Rewards' -> ['orbit']): 4+ letters, not generic marketing words."""
    import re
    return [t for t in re.findall(r"[a-z0-9]+", (display_name or "").lower()) if len(t) >= 4 and t not in _GENERIC_WORDS]

def brand_mismatch(display_name: str | None, address: str | None) -> bool:
    """True when the display name names a brand that does not appear in the sender's domain (e.g. 'Orbit Rewards' from
    points-mail.example). Real companies often send through other domains, so this is a 'verify it' flag, not a verdict."""
    import re
    if not address or address.startswith("@"):
        return False
    tokens = brand_tokens(display_name)
    if not tokens:
        return False
    domain = re.sub(r"[^a-z0-9]", "", domain_of(address))
    if any(t in domain for t in tokens):
        return False
    words = (display_name or "").split()
    if len(words) == 2 and all(w[:1].isupper() and w[1:].islower() and w.lower() not in _GENERIC_WORDS for w in words):  # looks like a person's name
        return False
    return True
