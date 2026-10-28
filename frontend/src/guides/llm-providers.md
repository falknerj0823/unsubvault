# Choose and connect an LLM

UnsubVault sends each email's **subject, sender and first 500 characters** to the model you pick, so the choice is also a privacy choice. **Settings → LLM** has a **Test connection** button for every option.

## Local (nothing leaves your machine): Ollama

1. Install Ollama and pull a model, for example `ollama pull qwen3:8b`.
2. Provider **Ollama**, leave the Base URL blank (`localhost` is translated to your computer automatically).
3. Click the Model field and pick from the installed list. Don't pick an embedding model.

Any OpenAI-style server works too (LM Studio, vLLM, OpenRouter, Groq): choose **OpenAI-compatible**, set its Base URL, and add an API key if it needs one.

## Cloud API keys

**OpenAI** or **Anthropic**: paste an API key from the provider's console. Usage is billed per request by the provider. Keys are stored encrypted and never shown again.

## Use your Claude subscription (Claude Code CLI)

Needs the image built with `INSTALL_AI_CLIS=true` (set in `.env`, then `docker compose up --build`).

1. In a normal terminal on your computer run `claude setup-token`.
2. Approve in the browser. The browser page shows a **login code** (it contains a `#`): paste that **into the terminal**.
3. The terminal then prints the **token**. Copy *that* into UnsubVault: **Provider → Claude subscription → Token**.
4. **Test connection**, then **Save**.

Common mistake: pasting the browser's login code instead of the token gives `401 Invalid bearer token`. Treat the token like a password.

## Use your ChatGPT subscription (Codex CLI) — experimental

1. Run `codex login` on your computer.
2. Start with the extra compose file so your login is mounted into the containers:
   `docker compose -f docker-compose.yml -f docker-compose.cli.yml up --build`
3. **Provider → ChatGPT subscription (Codex CLI) → Test connection.**

The CLI's options were checked against the real Codex program, but it hasn't been tried with a live ChatGPT login by the author.
