# Security

STRATA must never become a secret store.

## Access tokens

- Each developer gets their own API access token (`strata_live_...` / `strata_dev_...`).
- Store in `STRATA_API_KEY` or `.strata/secrets.json` (gitignored).
- v0 development servers accept only tokens listed in `STRATA_API_KEYS`.
- Production key persistence stores **hashed** keys only; raw key shown once at creation.

## Never capture

- Passwords, API keys, private keys, OAuth secrets
- Raw `.env` files or credential values
- Full terminal logs unless explicitly requested and scrubbed

## Transport

- HTTPS only in production
- `Authorization: Bearer <token>` on all non-health endpoints
- API bound to localhost behind Apache; public TLS at edge
