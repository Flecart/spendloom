# Spendloom

Spendloom is a private, self-hosted receipt inbox and spending companion for one person. Send a receipt from the web or Telegram, keep the original locally, and turn it into a reviewable expense without giving a cloud service access to your whole ledger.

![Spendloom woven-receipt social art](assets/spendloom-social.png)

![Synthetic Spendloom dashboard](assets/spendloom-dashboard-demo.png)

## Why Spendloom

- Capture JPEG, PNG, WebP, HEIC, and PDF receipts from the web or Telegram.
- Keep front/back images, supporting slips, or separate pages together as one receipt and one expense.
- Choose OpenAI, Anthropic, Gemini, or ChatGPT subscription access through the Codex CLI for receipt extraction and Telegram conversation; provider switches do not lose local chat context.
- Review uncertain records, remember merchant rules, normalise to EUR, and export Ramp-shaped CSV.
- Ask Telegram to find, total, create, or correct expenses. Calculations and database writes stay on the server.
- Keep data in your own SQLite database and receipt directory.

## AI provider matrix

| Provider | Receipt extraction | Telegram tools |
| --- | --- | --- |
| OpenAI | Structured Responses API | Function calling |
| Codex CLI | Structured final output | Structured tool requests |
| Anthropic | JSON extraction | Tool use |
| Gemini | JSON extraction | Function declarations |

Set `AI_PROVIDER`, `AI_MODEL`, and the matching credential. API providers use their corresponding API key; the `codex` provider uses the ChatGPT sign-in described below. `CHAT_MODEL` is optional and otherwise reuses `AI_MODEL`. Without a configured credential, receipts remain safely stored for manual review.

### Use a ChatGPT subscription

A ChatGPT Plus subscription is not an OpenAI API key and cannot authenticate ordinary calls to `api.openai.com`. Spendloom's `codex` provider instead invokes the supported Codex CLI, which can use a ChatGPT sign-in and included subscription access:

```dotenv
AI_PROVIDER=codex
AI_MODEL=gpt-5.6-luna
CODEX_AUTH_DIR=/absolute/private/path/to/spendloom-codex-auth
```

Run `./install.sh` and choose `codex`; the installer builds the Codex-enabled worker and starts a device-code login when the credential directory is empty. For an existing deployment, rebuild and sign in explicitly:

```bash
mkdir -p .codex-auth
chmod 700 .codex-auth
./scripts/codex-login.sh
docker compose up -d --force-recreate worker
docker compose exec worker codex login status
```

When changing `AI_PROVIDER` on an existing deployment, always rebuild and force-recreate the worker so the running container matches the selected provider.
The login helper also repairs credential-directory ownership, checks that `/codex` is writable from inside the worker, and then starts a fresh device-code flow. If a device page stalls, stop the command, let that one-time code expire, and rerun the helper rather than reusing the code.

Keep the credential directory private: `auth.json` contains refreshable access tokens. It is excluded from Git, Docker build context, and Spendloom data backups. This mode is intended only for a trusted, private, single-user deployment. Codex runs are ephemeral, read-only, receive a minimal process environment, and are instructed not to use runtime tools; API keys remain the recommended authentication method for unattended or public automation.

## Telegram demo

After claiming the private bot, send a receipt and then write: “make that business”, “what did I spend on travel in July?”, or “export this year”. Telegram albums are processed as one receipt. When another standalone document or album arrives while a receipt is active, choose **Add to current receipt** or **Start new receipt**; adding preserves the current conversation. An unanswered choice is processed separately after ten minutes without replacing the active context. Spendloom retains at most eight user/assistant exchanges for 24 hours. `/new` clears that context and `/context` shows the active receipt, document count, and retained message count. Deleting, archiving, replacing, and bulk changes always require a one-use Confirm/Cancel button that expires after ten minutes.

In the web uploader, select multiple files and enable **These files belong to one receipt** to extract them together. Separate receipts remain the default. Group limits can be adjusted with `MAX_RECEIPT_DOCUMENTS`, `MAX_RECEIPT_TOTAL_MB`, and `MAX_RECEIPT_TOTAL_PAGES`.

For the strongest single-user setup, send `/id` to the bot, put the returned numeric value in `TELEGRAM_ALLOWED_USER_ID` in `.env`, then restart the Telegram service with `docker compose --profile telegram up -d --force-recreate telegram`. That allowlist is checked on every message and button callback, so no other Telegram account can claim or use the bot, even if it knows a claim code. It also lets the configured account reclaim a copied database with a stale bot owner.

## Architecture and privacy

The web service accepts files and runs migrations, the worker performs extraction and chat jobs, and the optional Telegram service talks directly to Telegram. They share a local SQLite database and `/data` receipt store. The model receives only bounded conversation history and data returned by explicitly requested, server-validated tools; it never receives SQL access.

Read the [architecture notes](docs/architecture.md) for the receipt lifecycle, failure model, and backup design.

## Install

On Ubuntu/Debian/Mint, Fedora/RHEL/Rocky/Alma, or Arch/Manjaro:

```bash
git clone https://github.com/Flecart/spendloom.git spendloom
cd spendloom
./install.sh
```

The installer detects Docker Engine/Compose v2, architecture, sudo, port conflicts, daemon state, and data ownership. It can install missing native Docker packages after confirmation, preserves an existing `.env`, backs up an existing database before rebuilding, starts the Telegram profile only when a token is supplied, and waits for health.

For CI or automation, use `SPENDLOOM_NONINTERACTIVE=1` plus `APP_PASSWORD`, `AI_PROVIDER`, the provider key (or a pre-provisioned `CODEX_AUTH_DIR`), `AI_MODEL`, `SPENDLOOM_PORT`, `APP_ORIGIN`, `PUID`, and `PGID`. Unsupported distributions should install Docker Engine and Compose v2 manually, then run the script.

To remove containers and networks while retaining `.env`, receipts, database, and backups:

```bash
./uninstall.sh
```

Use `--remove-images` to remove local images. `--purge` creates a final archive outside the install directory and requires the exact phrase `PURGE SPENDLOOM` before removing private data.

## Manual development and deployment

```bash
cp .env.example .env
# Set a strong APP_PASSWORD, SESSION_SECRET, provider authentication, and optionally a Telegram token.
docker compose up -d --build web worker
docker compose --profile telegram up -d telegram  # optional
```

Visit `http://localhost:8080`. For LAN use, set both `SPENDLOOM_PORT` and `APP_ORIGIN`; do not expose this plain-HTTP setup to the public internet. Put HTTPS and additional access controls in front of any public deployment.

```bash
uv venv .venv
. .venv/bin/activate
uv pip install -e '.[test]'
uv run pytest
cd frontend && npm install && npm run build
```

## Backups, limitations, and roadmap

Run `docker compose exec web python -m receipt_ledger.backup /data/backups` for a transactionally consistent database-and-files archive. Store it encrypted elsewhere.

Spendloom is home-hosted and single-user. It does not transcribe voice notes, accept arbitrary documents as chat input, synchronise QuickBooks, calculate tax, or provide financial advice. Planned work includes richer review shortcuts, more export mappings, accessibility refinement, and optional encrypted off-site backup guidance.

## Contributing and support

Spendloom is GPL-3.0-only. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [SUPPORT.md](SUPPORT.md), [CHANGELOG.md](CHANGELOG.md), and [asset attribution](ASSETS.md). Please do not post receipts, API keys, or database copies in issues.
