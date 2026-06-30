# Security

STRATA must never become a secret store.

## Access tokens

- Each developer gets their own API access token (`strata_live_...` / `strata_dev_...`).
- Store in `STRATA_API_KEY` or `.strata/secrets.json` (gitignored).
- Workstation installers create placeholder secret files; they do not grant access.
- Production key persistence stores **hashed** keys only; raw keys are shown only once at creation.
- `STRATA_API_KEYS` is a bootstrap/development compatibility path. Prefer hashed per-user keys for production.

## Never capture

- Passwords, API keys, private keys, OAuth secrets
- Raw `.env` files or credential values
- Full terminal logs unless explicitly requested and scrubbed

## Transport

- HTTPS only in production
- `Authorization: Bearer <token>` on all non-health endpoints
- API bound to localhost behind Apache or Nginx; public TLS at edge

## Provisioning

- Create the first admin key with `api/scripts/seed_key.py`.
- Create additional keys with `POST /v1/api-keys` using an admin token.
- Send install commands and raw tokens through separate channels when onboarding.
- Revoke tokens with `POST /v1/api-keys/{id}/revoke` when devices are lost or users leave.

See [Provisioning](provisioning.md).
