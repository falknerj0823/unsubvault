import asyncio, os, tempfile
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from app.core import app_settings
from app.core.config import settings
from app.core.crypto import decrypt
from app.core.database import SessionLocal
from app.models.llm_config import LLMProfile

PROVIDERS = ["openai", "anthropic", "ollama", "openai_compatible", "claude_cli", "codex_cli"]
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini", "anthropic": "claude-haiku-5-5", "ollama": "",
    "openai_compatible": "", "claude_cli": "claude-haiku-5-5", "codex_cli": "",
}
CLI_TIMEOUT = 180
# The CLIs get only what they need to run, never the app's own secrets (SECRET_KEY, database URL, other providers' keys).
_CLI_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS")
_CLI_ENV_FORCE = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"}

def container_url(url: str) -> str:
    """Inside Docker, 'localhost' is the container itself; users mean their host machine."""
    if not url:
        return url
    parts = urlsplit(url)
    if parts.hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        netloc = "host.docker.internal" + (f":{parts.port}" if parts.port else "")
        return urlunsplit(parts._replace(netloc=netloc))
    return url

@dataclass
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key: str

def _from_row(row: LLMProfile) -> LLMSettings:
    try:
        key = decrypt(row.api_key_encrypted) if row.api_key_encrypted else ""
    except ValueError:  # SECRET_KEY changed: treat the key as not set so the user can enter it again
        key = ""
    return LLMSettings(row.provider, row.model or DEFAULT_MODELS.get(row.provider, ""), row.base_url or "", key)

def load_profiles() -> dict[str, LLMSettings]:
    """Every saved per-provider configuration, keyed by provider."""
    db = SessionLocal()
    try:
        return {r.provider: _from_row(r) for r in db.query(LLMProfile).all()}
    finally:
        db.close()

def load_llm_settings() -> LLMSettings:
    """The active provider's saved profile; falls back to the .env values so existing setups keep working."""
    active = app_settings.get_internal("llm_active_provider")
    if active:
        return load_profiles().get(active) or LLMSettings(active, DEFAULT_MODELS.get(active, ""), "", "")
    provider = settings.llm_provider
    key = {"openai": settings.openai_api_key, "anthropic": settings.anthropic_api_key}.get(provider, "")
    if provider == "ollama":
        return LLMSettings(provider, settings.ollama_model, settings.ollama_base_url, "")
    return LLMSettings(provider, DEFAULT_MODELS.get(provider, ""), "", key)

async def complete(system: str, prompt: str, cfg: LLMSettings | None = None) -> str:
    cfg = cfg or load_llm_settings()
    model = cfg.model or DEFAULT_MODELS.get(cfg.provider, "")
    if cfg.provider in ("openai", "openai_compatible"):
        return await _openai(cfg, model, system, prompt)
    if cfg.provider == "anthropic":
        return await _anthropic(cfg, model, system, prompt)
    if cfg.provider == "ollama":
        return await _ollama(cfg, model, system, prompt)
    if cfg.provider == "claude_cli":
        return await _claude_cli(cfg, model, system, prompt)
    if cfg.provider == "codex_cli":
        return await _codex_cli(cfg, model, system, prompt)
    raise ValueError(f"Unknown LLM provider: {cfg.provider}")

async def _openai(cfg, model, system, prompt) -> str:
    from openai import AsyncOpenAI
    if cfg.provider == "openai_compatible" and not cfg.base_url:
        raise ValueError("Base URL is required for OpenAI-compatible providers")
    client = AsyncOpenAI(api_key=cfg.api_key or "not-needed", base_url=container_url(cfg.base_url) or None)
    kwargs = {"response_format": {"type": "json_object"}} if cfg.provider == "openai" else {}
    r = await client.chat.completions.create(model=model, **kwargs,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
    return r.choices[0].message.content

async def _anthropic(cfg, model, system, prompt) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=cfg.api_key)
    r = await client.messages.create(model=model, max_tokens=1024, system=system,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

def _ollama_url(cfg) -> str:
    return container_url(cfg.base_url or "http://localhost:11434").rstrip("/")

async def list_models(cfg: LLMSettings) -> list[str]:
    """Ask the provider which models it offers. Only Ollama and OpenAI-style servers can be asked."""
    if cfg.provider == "ollama":
        import httpx
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(f"{_ollama_url(cfg)}/api/tags")
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
    if cfg.provider in ("openai", "openai_compatible"):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=cfg.api_key or "not-needed", base_url=container_url(cfg.base_url) or None, timeout=10)
        return sorted(m.id for m in (await client.models.list()).data)
    return []

async def _ollama(cfg, model, system, prompt) -> str:
    import httpx
    installed = await list_models(cfg)
    if not model:
        raise ValueError(f"Pick a model. Installed in Ollama: {', '.join(installed) or 'none (run `ollama pull <model>`)'}")
    if model not in installed and f"{model}:latest" not in installed:
        raise ValueError(f"Model '{model}' is not installed in Ollama. Installed: {', '.join(installed) or 'none'}")
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(f"{_ollama_url(cfg)}/api/chat",
            json={"model": model, "stream": False,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["message"]["content"]

async def _run_cli(argv: list[str], stdin: str, env_extra: dict[str, str]) -> str:
    """Run a CLI with no shell, in an empty temp dir, prompt on stdin, hard timeout."""
    with tempfile.TemporaryDirectory() as cwd:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env={**{k: os.environ[k] for k in _CLI_ENV_KEEP if k in os.environ}, **_CLI_ENV_FORCE, **env_extra},
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            raise ValueError(f"'{argv[0]}' is not installed in this image. Rebuild with INSTALL_AI_CLIS=true (see README)")
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), CLI_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            raise ValueError(f"{argv[0]} timed out after {CLI_TIMEOUT}s")
    if proc.returncode != 0:
        detail = (err.decode().strip() or out.decode().strip())[-400:]  # claude prints errors on stdout
        raise ValueError(f"{argv[0]} exited {proc.returncode}: {detail}")
    return out.decode()

async def _claude_cli(cfg, model, system, prompt) -> str:
    # Email text is untrusted: --tools "" disables every tool so injected instructions cannot act.
    argv = ["claude", "-p", "--output-format", "text", "--tools", "", "--effort", "low", "--system-prompt", system]
    if model:
        argv += ["--model", model]
    token = cfg.api_key.strip()
    env = {"CLAUDE_CODE_OAUTH_TOKEN": token} if token else {}
    try:
        return await _run_cli(argv, prompt, env)
    except ValueError as e:
        if "#" in token:
            raise ValueError(f"{e} | That looks like the one-time login code from the browser page (it contains '#'), "
                             "not the token. Paste that code into the terminal; the terminal then prints the real token to paste here.") from e
        raise

async def _codex_cli(cfg, model, system, prompt) -> str:
    # Codex has no system-prompt flag; fold it into the prompt. Read-only sandbox, no git needed.
    argv = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check"]
    if model:
        argv += ["-m", model]
    argv.append("-")
    return await _run_cli(argv, f"{system}\n\n{prompt}", {})
