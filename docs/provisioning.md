# Provisioning

Provisioning is the owner/admin path for creating access tokens and onboarding teammates. STRATA install scripts are public bootstrap scripts; access is granted only by a valid `strata_live_...` or `strata_dev_...` token.

## Token Model

- Every developer should have their own token.
- Raw tokens are shown once when created.
- Production tokens should use the `strata_live_` prefix.
- Development tokens can use the `strata_dev_` prefix.
- Tokens are stored hashed in PostgreSQL.
- Normal users need `memory:read`, `memory:write`, and `memory:sync`.
- Admin users also need `keys:manage` and `admin`.

Never put tokens in Git, URLs, shell history screenshots, or installer links.

## Bootstrap The First Admin

On the API host:

```bash
cd /var/www/cxl-strata/api
source .venv/bin/activate
set -a && source .env && set +a
python scripts/seed_key.py \
  --org-slug example-org \
  --org-name "Example Org" \
  --actor-name "Admin Name" \
  --actor-email admin@example.com \
  --key-name bootstrap-admin \
  --prefix strata_live_
```

The command prints the raw token once:

```text
Save this access token now (shown once):
strata_live_...
```

Save it in a password manager.

## Create A Teammate Token

Use an admin token with `keys:manage` and `admin`.

```bash
export STRATA_ADMIN_KEY="strata_live_admin_token"

curl -fsS https://strata.example.com/v1/api-keys \
  -H "Authorization: Bearer ${STRATA_ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "duy-workstation",
    "prefix": "strata_live_",
    "scopes": ["memory:read", "memory:write", "memory:sync"]
  }'
```

The response includes `raw_key` once. Send it through a secure channel such as 1Password or a secure DM. Do not send it in the same message as public install instructions if your threat model requires separation.

## Verify A Token

```bash
export STRATA_API_KEY="strata_live_user_token"

curl -fsS https://strata.example.com/v1/whoami \
  -H "Authorization: Bearer ${STRATA_API_KEY}"
```

Expected response includes the actor, organization, and scopes.

## List Keys

```bash
curl -fsS https://strata.example.com/v1/api-keys \
  -H "Authorization: Bearer ${STRATA_ADMIN_KEY}"
```

The list shows key metadata, prefixes, scopes, active status, and last use data. It does not show raw tokens.

## Revoke A Key

```bash
curl -fsS -X POST https://strata.example.com/v1/api-keys/KEY_ID/revoke \
  -H "Authorization: Bearer ${STRATA_ADMIN_KEY}"
```

Revoke tokens when a device is lost, a teammate leaves, or a token may have leaked.

## Onboarding Message Shape

Send teammates two things:

1. Public install URL and organization slug.
2. Their personal `strata_live_...` token through a secure channel.

Example:

```text
Install STRATA:
  https://strata.example.com/install.sh
  https://strata.example.com/install.ps1

Org:
  example-org

Your personal token is in 1Password.

After install, run:
  strata whoami
```

See [client installation](client-installation.md) for platform commands.

## Bootstrap Env Keys

`STRATA_API_KEYS` exists for bootstrap and development compatibility:

```env
STRATA_API_KEYS=strata_dev_example
```

For production rollout, prefer hashed per-user keys created with `seed_key.py` or `/v1/api-keys`. Keep `STRATA_API_KEYS` empty after bootstrap unless you intentionally need a temporary emergency key.
