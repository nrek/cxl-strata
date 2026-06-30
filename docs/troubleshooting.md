# Troubleshooting

Use this page when install, auth, sync, MCP, or the local app does not behave as expected.

## API Health Fails

Check the central API directly:

```bash
curl -fsS https://strata.example.com/health
```

PowerShell:

```powershell
irm https://strata.example.com/health
```

If the public URL fails on the server, test localhost:

```bash
curl -fsS http://127.0.0.1:8015/health
sudo systemctl status cxl-strata-api
journalctl -u cxl-strata-api -n 100 --no-pager
```

For reverse proxy issues:

```bash
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## `strata` Command Not Found

Use the module form:

```bash
python -m cxl_strata.cli --help
python -m cxl_strata.cli whoami
```

Windows:

```powershell
python -m cxl_strata.cli --help
python -m cxl_strata.cli whoami
```

Then reopen the terminal. The installer adds the Python user Scripts directory to PATH when possible.

Manual reinstall:

```bash
python -m pip install --user --upgrade "git+https://github.com/YOUR_ORG/cxl-strata.git@main#subdirectory=cli"
```

## Python, pip, Or Git Missing

Check:

```bash
python --version
python -m pip --version
git --version
```

On macOS, `python3` may be the command:

```bash
python3 --version
python3 -m pip --version
```

On Windows, install Python 3.10+ and Git for Windows, then open a new PowerShell session.

## `401 Unauthorized` Or `Unknown access token`

Check the token:

```bash
strata whoami
```

Token locations:

- `STRATA_API_KEY`
- `.strata/secrets.json`
- `~/.strata/secrets.json`
- `%USERPROFILE%\.strata\secrets.json` on Windows
- `~/.strata/orgs/{alias}.json` for named org profiles

Verify with curl:

```bash
curl -fsS https://strata.example.com/v1/whoami \
  -H "Authorization: Bearer strata_live_your_token"
```

PowerShell:

```powershell
$h = @{ Authorization = "Bearer strata_live_your_token" }
irm https://strata.example.com/v1/whoami -Headers $h
```

Common causes:

- Placeholder token still in `secrets.json`.
- Token has trailing whitespace.
- Token belongs to another STRATA installation.
- Token was revoked.
- Token lacks required scopes.

## Missing `.strata/config.json`

Run from the repo root:

```bash
strata init --api https://strata.example.com --org example-org --project my-project --repo my-repo
```

The installer can also initialize a repo:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- --org example-org --init --project my-project
```

PowerShell:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init -Project my-project
```

## `strata sync` Reports Failures

Check the local queue:

```bash
cat .strata/events.jsonl
cat .strata/failed.jsonl
```

PowerShell:

```powershell
Get-Content .strata\events.jsonl
Get-Content .strata\failed.jsonl
```

Common causes:

- API is unreachable.
- Token lacks `memory:sync` or `memory:write`.
- Payload contains secret-like content.
- `.strata/config.json` points at the wrong API or org.

After successful sync, rows move to `.strata/synced.jsonl`.

## `422` Secret Detection

STRATA rejects obvious secret patterns such as private keys, raw `API_KEY=...` values, Stripe-style keys, AWS access keys, and OAuth secrets.

Write notes like this:

```text
Good: OAuth depends on GOOGLE_CLIENT_ID and APP_URL alignment.
Bad: GOOGLE_CLIENT_SECRET=actual-secret-value
```

## Local SQLite Database Missing

The local SQLite cache is created by workspace indexing, not by `strata init`.

From the workspace root:

```bash
strata index
ls .md/workspace_index.sqlite
```

PowerShell:

```powershell
strata index
Test-Path .md\workspace_index.sqlite
```

If STRATA cannot find the workspace root:

```bash
export STRATA_WORKSPACE_ROOT=/path/to/workspace
strata index
```

PowerShell:

```powershell
$env:STRATA_WORKSPACE_ROOT = "D:\projects"
strata index
```

## Localhost App Opens But Looks Empty

The app browses local SQLite. Refresh the local cache:

```bash
strata index
strata pull --project my-project
strata app --open
```

If port `8765` is in use:

```bash
strata app --port 8766 --open
```

## Shared Search Returns Nothing

Confirm the event reached the central API:

```bash
strata sync
strata search "exact title words"
strata recent --days 7
```

Search is text-based. Try words from the title, summary, details, tags, project, repo, environment, or event type.

## MCP Does Not Show STRATA Tools

Check MCP package install:

```bash
python -m strata_mcp.server
```

The command starts a stdio server and may appear to wait for input. Stop it with `Ctrl+C`.

Check config:

```json
{
  "mcpServers": {
    "strata": {
      "command": "python",
      "args": ["-m", "strata_mcp.server"],
      "env": {
        "STRATA_API_URL": "https://strata.example.com",
        "STRATA_API_KEY": "strata_live_your_token"
      }
    }
  }
}
```

Restart the MCP client after changing config.

## PowerShell Installer Issues

If the one-liner fails:

```powershell
irm https://strata.example.com/install.ps1 -OutFile "$env:TEMP\install-strata.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\install-strata.ps1"
```

If PATH does not update, reopen PowerShell or run:

```powershell
python -m cxl_strata.cli whoami
```

## SSL Or Certificate Errors

- Use `https://` for production API URLs.
- Confirm the certificate covers the hostname users configured.
- For local development only, use `http://127.0.0.1:8015`.

## Reverse Proxy 502

Usually this means Apache or Nginx cannot reach Uvicorn.

Check:

```bash
sudo systemctl status cxl-strata-api
curl -fsS http://127.0.0.1:8015/health
journalctl -u cxl-strata-api -n 100 --no-pager
```

Confirm the proxy target is `http://127.0.0.1:8015`.
