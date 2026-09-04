# Security policy

Do not report vulnerabilities in public issues. Send a concise reproduction and impact description to the project maintainer through the private contact configured for the release. Do not include real receipts, credentials, email contents, or live database files. Supported releases receive fixes on a best-effort basis; rotate exposed API keys and Telegram tokens immediately.

The optional Gmail connector uses a read-only scope, but Google cannot constrain that scope to the configured sender allowlist. Treat `GMAIL_CLIENT_SECRET`, `GMAIL_TOKEN_ENCRYPTION_KEY`, and database backups as credentials. If any are exposed, disconnect Gmail to revoke the refresh token, rotate the OAuth secret and encryption key, and reconnect.
