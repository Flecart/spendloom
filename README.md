<div align="center">

# Spendloom

**A private, self-hosted receipt inbox and spending companion for one person.**

Snap a receipt from the web or Telegram, keep a compact copy on your own disk, and let an AI model of your choice turn it into a reviewable expense — without handing your whole ledger to a cloud service.

[![CI](https://github.com/Flecart/spendloom/actions/workflows/ci.yml/badge.svg)](https://github.com/Flecart/spendloom/actions/workflows/ci.yml)
[![License: GPL-3.0-only](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Self-hosted](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED.svg)

![Spendloom woven-receipt social art](assets/spendloom-social.png)

</div>

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [AI providers](#ai-providers)
- [Telegram bot](#telegram-bot)
- [Income, recurring items, and invoices](#income-recurring-items-and-invoices)
- [Gmail import (optional)](#gmail-import-optional)
- [Privacy and security model](#privacy-and-security-model)
- [Backups and uninstalling](#backups-and-uninstalling)
- [Development](#development)
- [Scope and roadmap](#scope-and-roadmap)
- [Contributing, support, and license](#contributing-support-and-license)

## Features

![Synthetic Spendloom dashboard](assets/spendloom-dashboard-demo.png)

**Capture**
- Upload JPEG, PNG, WebP, HEIC, and PDF receipts from the web app or Telegram.
- Group front/back photos, supporting slips, or separate pages into one receipt and one expense.
- Stored images are compressed by default to keep the receipt directory small.

**Extract and review**
- AI extraction with OpenAI, Anthropic, Gemini, or a ChatGPT subscription via the Codex CLI.
- Uncertain records go to a review queue. Receipts dated more than two weeks before upload always do.
- Merchant rules are remembered, and amounts are normalised to EUR using ECB reference rates.
- Export Ramp-compatible CSV.

**Ask and act**
- Chat with the Telegram bot to find, total, create, or correct expenses. All calculations and database writes happen on the server.
- Destructive or bulk actions always require an expiring one-time confirmation.

**Plan your money**
- Track confirmed income, recurring expenses and earnings, contracts, and externally issued invoices.
- Allocate full or partial payments to invoices. See cash flow, outstanding receivables, and upcoming obligations.
- Optionally import receipts from exact allowlisted Gmail senders.

**Own your data**
- Everything lives in a local SQLite database and receipt directory on your machine.
- If no AI credential is configured, receipts are still stored safely and wait for manual review.

## Quick start

Requirements: a Linux host with Docker Engine and Docker Compose v2. The installer can install Docker for you on Ubuntu/Debian/Mint, Fedora/RHEL/Rocky/Alma, and Arch/Manjaro.

```bash
git clone https://github.com/Flecart/spendloom.git
cd spendloom
./install.sh
```

The installer:

- checks Docker, Compose, architecture, sudo, port conflicts, daemon state, and data ownership
- offers to install missing native Docker packages
- preserves an existing `.env`
- backs up an existing database before rebuilding
- starts the Telegram service only when you supply a bot token
- waits until the app is healthy

Then open <http://localhost:8080> and sign in with the password you chose.

<details>
<summary><strong>Manual setup with Docker Compose</strong></summary>

```bash
cp .env.example .env
# Edit .env: set a strong APP_PASSWORD and SESSION_SECRET, your AI provider
# credentials, and optionally TELEGRAM_BOT_TOKEN.
docker compose up -d --build web worker
docker compose --profile telegram up -d telegram   # optional
```

</details>

<details>
<summary><strong>Non-interactive install (CI or automation)</strong></summary>

Set `SPENDLOOM_NONINTERACTIVE=1` and provide `APP_PASSWORD`, `AI_PROVIDER`, the matching provider key (or a pre-provisioned `CODEX_AUTH_DIR`), `AI_MODEL`, `SPENDLOOM_PORT`, `APP_ORIGIN`, `PUID`, and `PGID` in the environment, then run `./install.sh`.

</details>

> [!WARNING]
> The default setup serves plain HTTP and is meant for `localhost` or a trusted LAN. For LAN use, set both `SPENDLOOM_PORT` and `APP_ORIGIN`. Do **not** expose it directly to the internet. Put HTTPS and extra access controls in front of any public deployment, and set `COOKIE_SECURE=true`.

## Configuration

All settings live in `.env`. See [`.env.example`](.env.example) for the full annotated list.

| Variable | Purpose |
| --- | --- |
| `APP_PASSWORD` | Web login password. It is hashed into the database on first start. |
| `SESSION_SECRET` | At least 32 random characters, used to sign session cookies. |
| `APP_ORIGIN`, `SPENDLOOM_PORT` | Public origin and host port of the web app. |
| `COOKIE_SECURE` | Set to `true` when served over HTTPS. |
| `TIMEZONE` | Used for dates and recurring reminders. |
| `PUID`, `PGID` | Host user/group that owns the data directory (`id -u`, `id -g`). |
| `AI_PROVIDER`, `AI_MODEL`, `CHAT_MODEL` | Extraction/chat provider and model. `CHAT_MODEL` defaults to `AI_MODEL`. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | API credential for the chosen provider. |
| `CODEX_AUTH_DIR`, `CODEX_TIMEOUT_SECONDS` | ChatGPT sign-in storage and timeout for the `codex` provider. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` | Optional Telegram bot and owner allowlist. |
| `MAX_RECEIPT_DOCUMENTS`, `MAX_RECEIPT_TOTAL_MB`, `MAX_RECEIPT_TOTAL_PAGES` | Limits for multi-document receipts. |
| `GMAIL_*` | Optional Gmail importer (see below). |

## AI providers

| Provider (`AI_PROVIDER`) | Receipt extraction | Telegram tools | Authentication |
| --- | --- | --- | --- |
| `openai` | Structured Responses API | Function calling | `OPENAI_API_KEY` |
| `anthropic` | JSON extraction | Tool use | `ANTHROPIC_API_KEY` |
| `gemini` | JSON extraction | Function declarations | `GEMINI_API_KEY` |
| `codex` | Structured final output | Structured tool requests | ChatGPT sign-in via Codex CLI |

Switching providers keeps local chat context. After changing `AI_PROVIDER` on an existing deployment, rebuild and recreate the worker so the running container matches the selected provider:

```bash
docker compose up -d --build --force-recreate worker
```

### Using a ChatGPT subscription (`codex`)

A ChatGPT Plus subscription is not an OpenAI API key and cannot authenticate calls to `api.openai.com`. The `codex` provider instead calls the official Codex CLI, which can use a ChatGPT sign-in and the access included in your subscription.

```dotenv
AI_PROVIDER=codex
AI_MODEL=gpt-5.6-luna
CODEX_AUTH_DIR=/absolute/private/path/to/spendloom-codex-auth
```

If you choose `codex`, `./install.sh` builds the Codex-enabled worker and starts a device-code login when the credential directory is empty. On an existing deployment:

```bash
mkdir -p .codex-auth && chmod 700 .codex-auth
./scripts/codex-login.sh
docker compose up -d --force-recreate worker
docker compose exec worker codex login status
```

The login helper fixes the credential directory's ownership, checks that `/codex` is writable inside the worker, and starts a fresh device-code flow. If the device page stalls, stop the command and let the code expire. Then rerun the helper instead of reusing the old code.

> [!IMPORTANT]
> `auth.json` in the credential directory contains refreshable access tokens. Keep it private. Spendloom excludes it from Git, the Docker build context, and data backups. Codex runs are ephemeral and read-only, get a minimal environment, and are told not to use runtime tools. Use this mode only for a trusted, private, single-user deployment. For unattended or public automation, use an API key instead.

## Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and set `TELEGRAM_BOT_TOKEN`.
2. Start the bot service: `docker compose --profile telegram up -d telegram`.
3. In **Settings → Telegram**, copy the `/claim <code>` command and send it to your bot in a private chat. Then **lock it to your account**: send `/id` to the bot and put the returned number in `TELEGRAM_ALLOWED_USER_ID`. Then recreate the service:

   ```bash
   docker compose --profile telegram up -d --force-recreate telegram
   ```

   The allowlist is checked on every message and button press, so no other account can claim or use the bot, even with a claim code. It also lets you reclaim a copied database that has a stale bot owner.

**Using it.** Send a receipt, then try messages like *"make that business"*, *"what did I spend on travel in July?"*, or *"export this year"*.

- **Albums** are processed as one receipt. If a new document arrives while a receipt is active, choose **Add to current receipt** or **Start new receipt**. If you don't answer within ten minutes, the new document is processed as a separate receipt.
- **Context** holds at most eight user/assistant exchanges for 24 hours. `/new` clears it. `/context` shows the active receipt, its document count, and the retained message count.
- **Confirmations**: deleting, archiving, replacing, and bulk changes always need a one-time Confirm/Cancel button that expires after ten minutes.

In the web uploader, select several files and enable **These files belong to one receipt** to extract them together. By default, each file is treated as its own receipt.

## Income, recurring items, and invoices

- **Recurring items** can be weekly, monthly, quarterly, or yearly. They create upcoming occurrences and Telegram reminders. Nothing is recorded until you confirm an amount, submit a receipt, or skip the occurrence. You can change the reminder time in Settings. It uses `TIMEZONE`.
- **Income** can be linked to a lightweight contract.
- **Receivables** store the totals and due dates of invoices you issued elsewhere. Allocate one or more same-currency payments to an invoice, and Spendloom marks it unpaid, partial, paid, or overdue.

Spendloom does not generate legal invoices or calculate taxes.

## Gmail import (optional)

Imports receipt attachments and sanitized email text from senders you explicitly allow.

1. Create a Google OAuth **web** client and register `${APP_ORIGIN}/api/integrations/gmail/oauth/callback` as its redirect URI.
2. Configure:

   ```dotenv
   GMAIL_CLIENT_ID=your-google-oauth-client-id
   GMAIL_CLIENT_SECRET=your-google-oauth-client-secret
   GMAIL_TOKEN_ENCRYPTION_KEY=a-separate-long-random-secret
   GMAIL_SYNC_MINUTES=5
   ```

3. Restart the `web` and `worker` services. Then go to **Settings → Gmail**, connect your account, and add exact sender addresses such as `noreply@iliad.it`.

Only messages that arrive after you connect are imported. There is no historical backfill.

> [!NOTE]
> Spendloom requests read-only Gmail access. Google does not offer sender-scoped OAuth, so the token technically allows reading the whole mailbox, but Spendloom fetches content only for exact sender-rule matches. Links, scripts, and remote images in emails are never fetched. The refresh token is stored encrypted, so keep `GMAIL_TOKEN_ENCRYPTION_KEY` safe and separate from your data backups.

## Privacy and security model

Spendloom runs as three small processes that share one SQLite database and one `/data` receipt store:

- **web** accepts uploads, serves the UI, and runs database migrations
- **worker** runs AI extraction and chat jobs
- **telegram** (optional) talks to the Telegram Bot API

A receipt is saved to disk and queued before any slow external call, so a failed AI request never loses it. Failed receipts can be retried or deleted from the UI.

The AI model only sees the receipt being processed, a bounded conversation history, and data returned by explicitly requested, server-validated tools. It never gets SQL access.

The [architecture notes](docs/architecture.md) cover the receipt lifecycle, failure model, and backup design. To report a vulnerability, follow [SECURITY.md](SECURITY.md).

## Backups and uninstalling

Create a transactionally consistent archive of the database and receipt files:

```bash
docker compose exec web python -m receipt_ledger.backup /data/backups
```

Encrypt it and store it somewhere else.

To remove containers and networks while keeping `.env`, receipts, the database, and backups:

```bash
./uninstall.sh                  # keep everything
./uninstall.sh --remove-images  # also remove local images
./uninstall.sh --purge          # archive, then delete all private data
```

`--purge` writes a final archive outside the install directory and asks you to type `PURGE SPENDLOOM` before it deletes anything.

## Development

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
uv venv .venv
. .venv/bin/activate
uv pip install -e '.[test]'
uv run pytest
```

Frontend (Node 22, React + Vite + MUI):

```bash
cd frontend
npm ci
npm run build
```

CI runs the backend tests, the frontend build, a Compose config check, a Semgrep scan, and a Trivy scan of the Docker image. Pushing a `v*` tag publishes a multi-arch image to `ghcr.io/flecart/spendloom`.

## Scope and roadmap

Spendloom is deliberately **home-hosted and single-user**. It does not transcribe voice notes, sync with QuickBooks, calculate tax, generate jurisdiction-compliant invoices, value stocks or other assets, or give financial advice.

Planned work:

- richer review shortcuts
- asset tracking
- more export mappings
- accessibility improvements
- guidance for encrypted off-site backups

See the [changelog](CHANGELOG.md) for release history.

## Contributing, support, and license

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md) first, and see [SUPPORT.md](SUPPORT.md) for where to ask questions.

> [!CAUTION]
> Never post real receipts, API keys, tokens, or database copies in issues or pull requests.

Spendloom is licensed under [GPL-3.0-only](LICENSE). Third-party asset attributions are in [ASSETS.md](ASSETS.md).
