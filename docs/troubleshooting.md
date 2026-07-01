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

This usually means the CLI installed successfully, but Python's user scripts directory is not on PATH for the current terminal.

First, prove the package is installed by using the module form:

```bash
python -m cxl_strata.cli --help
python -m cxl_strata.cli whoami
```

macOS/Linux may use `python3`:

```bash
python3 -m cxl_strata.cli --help
python3 -m cxl_strata.cli whoami
```

Windows PowerShell:

```powershell
python -m cxl_strata.cli --help
python -m cxl_strata.cli whoami
```

If the module form works, fix PATH.

### Linux, macOS, WSL, Bash, Zsh

Find Python's user bin directory:

```bash
python3 -m site --user-base
```

The `strata` command is usually in:

```text
$(python3 -m site --user-base)/bin
```

Add it for the current terminal:

```bash
export PATH="$(python3 -m site --user-base)/bin:$PATH"
```

Persist it:

```bash
printf '\n# STRATA pip user bin\nexport PATH="$(python3 -m site --user-base)/bin:$PATH"\n' >> ~/.profile
```

For zsh, use `~/.zshrc` instead:

```bash
printf '\n# STRATA pip user bin\nexport PATH="$(python3 -m site --user-base)/bin:$PATH"\n' >> ~/.zshrc
```

For bash, use `~/.bashrc` if your terminal reads it:

```bash
printf '\n# STRATA pip user bin\nexport PATH="$(python3 -m site --user-base)/bin:$PATH"\n' >> ~/.bashrc
```

Open a new terminal and verify:

```bash
which strata
strata whoami
```

### Windows PowerShell

Find Python's user Scripts directory:

```powershell
$scriptsDir = Join-Path (python -m site --user-base) "Scripts"
$scriptsDir
```

Add it for the current PowerShell session:

```powershell
$env:Path = "$scriptsDir;$env:Path"
```

Persist it for future terminals:

```powershell
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ';') -notcontains $scriptsDir) {
  [Environment]::SetEnvironmentVariable("Path", "$scriptsDir;$userPath", "User")
}
```

Also add it to your PowerShell profile:

```powershell
New-Item -ItemType Directory -Force -Path (Split-Path $PROFILE -Parent) | Out-Null
Add-Content -Path $PROFILE -Value @"

# STRATA pip user Scripts
`$__strataScripts = Join-Path (python -m site --user-base 2>`$null) 'Scripts'
if (`$__strataScripts -and (Test-Path `$__strataScripts)) { `$env:Path = "`$__strataScripts;" + `$env:Path }
"@
```

Open a new PowerShell window and verify:

```powershell
Get-Command strata
strata whoami
```

The installer tries to do these PATH updates automatically and marks its profile block with `STRATA_PATH_BLOCK_BEGIN` / `STRATA_PATH_BLOCK_END`. If your terminal was already open before install, reopening it is often enough.

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

Run from the workspace root:

```bash
strata init --api https://strata.example.com --org example-org
```

The installer can also initialize the workspace:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- --org example-org --init
```

PowerShell:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
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

The local SQLite cache is created by workspace indexing and by the localhost app bootstrap.

The all-in-one post-key bootstrap is:

```bash
python -m cxl_strata.cli --init
```

It hardens PATH, creates `.md/workspace_index.sqlite`, and opens the browser UI.

If the command fails with `No such option: --init`, the workstation is still running an older installed CLI. On Windows, use the installer bootstrap fallback:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

Then retry:

```powershell
python -m cxl_strata.cli --help
```

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

No-PATH fallback:

```bash
python -m cxl_strata.cli index
python -m cxl_strata.cli app --open
```

The install scripts also run `index` automatically when you pass `--init` / `-Init`.

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

The app browses local SQLite. It creates the database if missing, but it can still look empty if there are no local docs or shared docs have not been pulled.

Refresh the local cache:

```bash
strata index
strata pull
strata app --open
```

STRATA indexes these local agent/project instruction files when present:

- Cursor: `.cursor/skills/**/SKILL.md`, `.cursor/rules/*.mdc`
- Claude: `CLAUDE.md`, `.claude/**/*.md`
- Codex: `AGENTS.md`, `.codex/**/*.md`

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

The installer also updates the user-level PATH environment variable. That is what makes `strata` visible to new PowerShell, Cursor, Claude, and Codex terminal sessions. Existing terminals may still need to be reopened.

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
