# Server Setup

This guide brings up the central STRATA API. The API is a FastAPI service that binds to localhost and is exposed through Apache or Nginx.

```text
Internet
  -> Apache or Nginx on 443
  -> Uvicorn on 127.0.0.1:8015
  -> PostgreSQL
```

Use `http://127.0.0.1:8015` for local development. Use HTTPS, a reverse proxy, and systemd for production.

## Requirements

- Ubuntu or another Linux host for production
- Python 3.10+
- PostgreSQL 16+
- Git
- Apache2 or Nginx
- A DNS name such as `strata.example.com`

## Local API

From the repo:

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
STRATA_ENV=development
STRATA_API_BASE_URL=http://127.0.0.1:8015
DATABASE_URL=postgresql+psycopg://strata:strata@127.0.0.1:5432/strata
API_KEY_PEPPER=change-me-in-production
STRATA_API_KEYS=strata_dev_example
BOOTSTRAP_ORG_SLUG=bootstrap-org
BOOTSTRAP_ORG_NAME=Bootstrap Organization
STRATA_PUBLIC_URL=http://127.0.0.1:8015
STRATA_CLIENT_GIT_URL=https://github.com/YOUR_ORG/cxl-strata.git
STRATA_CLIENT_GIT_REF=main
STRATA_DEFAULT_ORG=bootstrap-org
```

Create the database and run migrations:

```bash
createdb strata
alembic upgrade head
python scripts/seed_key.py --org-slug bootstrap-org --prefix strata_dev_
```

Start the API:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8015
```

Verify:

```bash
curl http://127.0.0.1:8015/health
```

Expected:

```json
{"status":"ok","service":"strata-api","storage":"postgres"}
```

## Production Layout

Recommended path:

```text
/var/www/cxl-strata
```

Create the app user and directory:

```bash
sudo useradd --system --home /var/www/cxl-strata --shell /usr/sbin/nologin strata || true
sudo mkdir -p /var/www/cxl-strata
sudo chown strata:strata /var/www/cxl-strata
```

Install server packages:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip postgresql apache2
```

Clone and install:

```bash
sudo -u strata git clone https://github.com/YOUR_ORG/cxl-strata.git /var/www/cxl-strata
cd /var/www/cxl-strata/api
sudo -u strata python3 -m venv .venv
sudo -u strata .venv/bin/pip install -r requirements.txt
sudo -u strata cp .env.example .env
```

Edit `/var/www/cxl-strata/api/.env`:

```env
STRATA_ENV=production
STRATA_API_BASE_URL=https://strata.example.com
DATABASE_URL=postgresql+psycopg://strata:STRONG_PASSWORD@127.0.0.1:5432/strata
API_KEY_PEPPER=GENERATE_A_LONG_RANDOM_STRING
STRATA_API_KEYS=
BOOTSTRAP_ORG_SLUG=example-org
BOOTSTRAP_ORG_NAME=Example Org
STRATA_PUBLIC_URL=https://strata.example.com
STRATA_CLIENT_GIT_URL=https://github.com/YOUR_ORG/cxl-strata.git
STRATA_CLIENT_GIT_REF=main
STRATA_DEFAULT_ORG=example-org
```

Create the database and apply migrations:

```bash
sudo -u postgres createuser strata
sudo -u postgres createdb -O strata strata
cd /var/www/cxl-strata/api
sudo -u strata .venv/bin/alembic upgrade head
sudo -u strata .venv/bin/python scripts/seed_key.py --org-slug example-org --prefix strata_live_
```

Save the raw key printed by `seed_key.py`. It is shown once.

## systemd

Create `/etc/systemd/system/cxl-strata-api.service`:

```ini
[Unit]
Description=STRATA central memory API
After=network.target postgresql.service

[Service]
User=strata
Group=strata
WorkingDirectory=/var/www/cxl-strata/api
EnvironmentFile=/var/www/cxl-strata/api/.env
ExecStart=/var/www/cxl-strata/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8015
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cxl-strata-api
sudo systemctl start cxl-strata-api
sudo systemctl status cxl-strata-api
curl -fsS http://127.0.0.1:8015/health
```

## Apache Reverse Proxy

Enable required modules:

```bash
sudo a2enmod proxy proxy_http ssl headers rewrite
```

Create `/etc/apache2/sites-available/strata.conf`:

```apache
<VirtualHost *:80>
    ServerName strata.example.com
    Redirect permanent / https://strata.example.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName strata.example.com

    SSLEngine on
    SSLCertificateFile      /etc/letsencrypt/live/strata.example.com/fullchain.pem
    SSLCertificateKeyFile   /etc/letsencrypt/live/strata.example.com/privkey.pem

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"

    ProxyPass        / http://127.0.0.1:8015/
    ProxyPassReverse / http://127.0.0.1:8015/

    ErrorLog ${APACHE_LOG_DIR}/strata-error.log
    CustomLog ${APACHE_LOG_DIR}/strata-access.log combined
</VirtualHost>
```

Enable and reload:

```bash
sudo a2ensite strata
sudo apache2ctl configtest
sudo systemctl reload apache2
curl -fsS https://strata.example.com/health
```

## Nginx Reverse Proxy

Install Nginx if you prefer it over Apache:

```bash
sudo apt install -y nginx
```

Create `/etc/nginx/sites-available/strata`:

```nginx
server {
    listen 80;
    server_name strata.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name strata.example.com;

    ssl_certificate     /etc/letsencrypt/live/strata.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/strata.example.com/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8015;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload:

```bash
sudo ln -sf /etc/nginx/sites-available/strata /etc/nginx/sites-enabled/strata
sudo nginx -t
sudo systemctl reload nginx
curl -fsS https://strata.example.com/health
```

## API Surface

Unauthenticated:

- `GET /health`
- `GET /install.sh`
- `GET /install.ps1`
- `GET /v1/client/manifest`

Authenticated:

- `GET /v1/whoami`
- `POST /v1/memory-events`
- `GET /v1/memory-events`
- `GET /v1/memory-events/{id}`
- `GET /v1/search`
- `GET /v1/projects/{project_slug}/context`
- `POST /v1/sync/batch`
- `POST /v1/documents`
- `GET /v1/documents`
- `GET /v1/documents/search`
- `GET /v1/documents/{id}`
- `POST /v1/documents/import-batch`

Admin key management:

- `POST /v1/api-keys`
- `GET /v1/api-keys`
- `POST /v1/api-keys/{id}/revoke`

All authenticated endpoints use:

```http
Authorization: Bearer strata_live_your_token
```

## MCP

The MCP server is installed on client workstations, not as part of the central API service. It reads from the central API through `STRATA_API_URL` and `STRATA_API_KEY`.

See [client installation](client-installation.md#mcp-for-ai-context-retrieval).

## Deploy Updates

```bash
cd /var/www/cxl-strata
sudo -u strata git pull
cd api
sudo -u strata .venv/bin/pip install -r requirements.txt
sudo -u strata .venv/bin/alembic upgrade head
sudo systemctl restart cxl-strata-api
sudo apache2ctl configtest
sudo systemctl reload apache2 || sudo systemctl restart apache2
```
