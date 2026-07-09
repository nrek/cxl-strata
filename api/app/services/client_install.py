"""Install script templates and manifest for local client bootstrap."""

from __future__ import annotations

from app.core.config import settings

INSTALL_SH = """#!/usr/bin/env bash
# STRATA local client installer — served from {public_url}
# Usage:
#   curl -fsSL {public_url}/install.sh | bash
#   curl -fsSL {public_url}/install.sh | bash -s -- --org your-org --init
set -euo pipefail

STRATA_API_URL="${{STRATA_API_URL:-{public_url}}}"
STRATA_GIT_URL="${{STRATA_GIT_URL:-{git_url}}}"
STRATA_GIT_REF="${{STRATA_GIT_REF:-{git_ref}}}"
STRATA_ORG="${{STRATA_ORG:-{default_org}}}"
DO_INIT=0
DO_CURSOR=0
PROJECT=""
REPO=""
ACTOR_NAME=""
ACTOR_EMAIL=""

usage() {{
  cat <<'EOF'
STRATA client installer

Options (also pass after bash -s --):
  --org ORG           Organization slug (default: {default_org})
  --project SLUG      Optional default project slug for memory capture
  --repo NAME         Optional repo name for memory capture
  --actor-name NAME   Actor display name for strata init
  --actor-email EMAIL Actor email for strata init
  --init              Run strata init in the current directory
  --cursor            Print Cursor MCP JSON snippet (~/.cursor/mcp.json)
  -h, --help          Show this help

After install, set your access token once:
  ~/.strata/secrets.json  →  {{"api_key": "strata_live_..."}}
  or export STRATA_API_KEY=strata_live_...

Verify: strata whoami
EOF
}}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --org) STRATA_ORG="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --actor-name) ACTOR_NAME="$2"; shift 2 ;;
    --actor-email) ACTOR_EMAIL="$2"; shift 2 ;;
    --init) DO_INIT=1; shift ;;
    --cursor) DO_CURSOR=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.10+ and retry." >&2
  exit 1
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "pip is required. Run: python3 -m ensurepip --upgrade" >&2
  exit 1
fi

PIP=(python3 -m pip install --user --upgrade --force-reinstall --no-cache-dir)
CLI_SPEC="git+${{STRATA_GIT_URL}}@${{STRATA_GIT_REF}}#subdirectory=cli"
MCP_SPEC="git+${{STRATA_GIT_URL}}@${{STRATA_GIT_REF}}#subdirectory=mcp"

echo "==> Installing STRATA CLI from ${{STRATA_GIT_URL}}@${{STRATA_GIT_REF}}"
"${{PIP[@]}}" "$CLI_SPEC"
echo "==> Installing STRATA MCP server"
"${{PIP[@]}}" "$MCP_SPEC"

STRATA_HOME="${{HOME}}/.strata"
mkdir -p "$STRATA_HOME"

GLOBAL_JSON="$STRATA_HOME/global.json"
if [[ ! -f "$GLOBAL_JSON" ]]; then
  cat >"$GLOBAL_JSON" <<EOF
{{
  "api_base_url": "${{STRATA_API_URL}}",
  "organization_slug": "${{STRATA_ORG}}",
  "installed_from": "{public_url}/install.sh"
}}
EOF
  echo "==> Wrote $GLOBAL_JSON"
else
  echo "==> Keeping existing $GLOBAL_JSON"
fi

SECRETS_JSON="$STRATA_HOME/secrets.json"
if [[ ! -f "$SECRETS_JSON" ]]; then
  cat >"$SECRETS_JSON" <<'EOF'
{{
  "api_key": "REPLACE_WITH_strata_live_OR_strata_dev_TOKEN"
}}
EOF
  chmod 600 "$SECRETS_JSON" 2>/dev/null || true
  echo "==> Wrote $SECRETS_JSON — edit api_key before syncing"
else
  echo "==> Keeping existing $SECRETS_JSON"
fi

# Ensure user-local scripts are on PATH for this session and future shells.
STRATA_BIN_DIR="$(python3 - <<'PY'
import os
import sysconfig

print(sysconfig.get_path('scripts', f'{{os.name}}_user') or '')
PY
)"
if [[ -z "$STRATA_BIN_DIR" ]]; then
  USER_BASE="$(python3 -m site --user-base 2>/dev/null || echo "$HOME/.local")"
  STRATA_BIN_DIR="$USER_BASE/bin"
fi

case ":$PATH:" in
  *":$STRATA_BIN_DIR:"*) ;;
  *) export PATH="$STRATA_BIN_DIR:$PATH" ;;
esac

PROFILE_FILES=("$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc")
PATH_BLOCK_BEGIN="# STRATA_PATH_BLOCK_BEGIN"
PATH_BLOCK_END="# STRATA_PATH_BLOCK_END"
for PROFILE_FILE in "${{PROFILE_FILES[@]}}"; do
  touch "$PROFILE_FILE" 2>/dev/null || true
  if [[ -w "$PROFILE_FILE" ]] && ! grep -Fq "$PATH_BLOCK_BEGIN" "$PROFILE_FILE" 2>/dev/null; then
    cat >>"$PROFILE_FILE" <<EOF

$PATH_BLOCK_BEGIN
# STRATA pip user bin
export PATH="$STRATA_BIN_DIR:\\$PATH"
$PATH_BLOCK_END
EOF
    echo "==> Added STRATA bin dir to $PROFILE_FILE"
  fi
done

STRATA_CMD=(strata)
if ! command -v strata >/dev/null 2>&1; then
  STRATA_CMD=(python3 -m cxl_strata.cli)
fi

if [[ "$DO_INIT" -eq 1 ]]; then
  INIT_ARGS=(init --api "$STRATA_API_URL" --org "$STRATA_ORG")
  [[ -n "$PROJECT" ]] && INIT_ARGS+=(--project "$PROJECT")
  [[ -n "$REPO" ]] && INIT_ARGS+=(--repo "$REPO")
  [[ -n "$ACTOR_NAME" ]] && INIT_ARGS+=(--actor-name "$ACTOR_NAME")
  [[ -n "$ACTOR_EMAIL" ]] && INIT_ARGS+=(--actor-email "$ACTOR_EMAIL")
  echo "==> Running ${{STRATA_CMD[*]}} ${{INIT_ARGS[*]}}"
  "${{STRATA_CMD[@]}}" "${{INIT_ARGS[@]}}"
  INDEX_ARGS=(index)
  echo "==> Initializing STRATA local SQLite index"
  "${{STRATA_CMD[@]}}" "${{INDEX_ARGS[@]}}" || echo "==> Warning: local SQLite index initialization failed; run: ${{STRATA_CMD[*]}} index"
  APP_ARGS=(app --open)
  echo "==> Opening STRATA localhost UI"
  "${{STRATA_CMD[@]}}" "${{APP_ARGS[@]}}"
fi

if [[ "$DO_CURSOR" -eq 1 ]]; then
  cat <<EOF

==> Cursor MCP snippet (~/.cursor/mcp.json):

{{
  "mcpServers": {{
    "strata": {{
      "command": "python",
      "args": ["-m", "strata_mcp.server"],
      "env": {{
        "STRATA_API_URL": "${{STRATA_API_URL}}",
        "STRATA_API_KEY": "strata_live_YOUR_TOKEN"
      }}
    }}
  }}
}}

Merge into existing mcpServers; set STRATA_API_KEY to your token (or rely on ~/.strata/secrets.json via env).
EOF
fi

cat <<EOF

STRATA client installed.

Next steps:
  1. Edit ~/.strata/secrets.json and set api_key to your strata_live_... token
     (or: export STRATA_API_KEY=strata_live_...)
  2. If this is a fresh shell with the latest CLI: python3 -m cxl_strata.cli --init
  3. If --init is unavailable, run the installer bootstrap instead:
     curl -fsSL {public_url}/install.sh | bash -s -- --init
     — or: strata init --api ${{STRATA_API_URL}} --org ${{STRATA_ORG}}
  4. Verify: strata whoami
     If this shell was already open before install: python3 -m cxl_strata.cli whoami
  5. --init initializes SQLite and installs .cursor/skills/strata/SKILL.md when a Cursor workspace is detected
  6. Refresh local index later with: strata index
  7. Open local UI: strata app --open
  8. Optional autostart (never installed silently): strata app install-autostart
  9. Optional Cursor MCP: re-run with --cursor for JSON snippet

Manifest: {public_url}/v1/client/manifest
EOF
"""

INSTALL_PS1 = """# STRATA local client installer — served from {public_url}
# Usage:
#   irm {public_url}/install.ps1 | iex
#   & ([scriptblock]::Create((irm {public_url}/install.ps1))) -Org your-org -Init
param(
  [string]$Org = "{default_org}",
  [string]$Project = "",
  [string]$Repo = "",
  [string]$ActorName = "",
  [string]$ActorEmail = "",
  [switch]$Init,
  [switch]$Cursor,
  [string]$ApiUrl = "{public_url}",
  [string]$GitUrl = "{git_url}",
  [string]$GitRef = "{git_ref}"
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$Path, [string]$Content) {{
  $utf8NoBom = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}}

function Require-Command($Name) {{
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {{
    throw "$Name is required but not found on PATH."
  }}
}}

Require-Command python
Require-Command pip

$CliSpec = "git+$GitUrl@$GitRef#subdirectory=cli"
$McpSpec = "git+$GitUrl@$GitRef#subdirectory=mcp"

Write-Host "==> Installing STRATA CLI"
python -m pip install --user --upgrade --force-reinstall --no-cache-dir $CliSpec
Write-Host "==> Installing STRATA MCP server"
python -m pip install --user --upgrade --force-reinstall --no-cache-dir $McpSpec

$StrataHome = Join-Path $env:USERPROFILE ".strata"
New-Item -ItemType Directory -Force -Path $StrataHome | Out-Null

$GlobalJson = Join-Path $StrataHome "global.json"
if (-not (Test-Path $GlobalJson)) {{
  $globalBody = (@{{ api_base_url = $ApiUrl; organization_slug = $Org; installed_from = "{public_url}/install.ps1" }} | ConvertTo-Json -Compress)
  Write-Utf8NoBom $GlobalJson $globalBody
  Write-Host "==> Wrote $GlobalJson"
}} else {{
  Write-Host "==> Keeping existing $GlobalJson"
}}

$SecretsJson = Join-Path $StrataHome "secrets.json"
if (-not (Test-Path $SecretsJson)) {{
  Write-Utf8NoBom $SecretsJson '{{"api_key":"REPLACE_WITH_strata_live_OR_strata_dev_TOKEN"}}'
  Write-Host "==> Wrote $SecretsJson — edit api_key before syncing"
}} else {{
  Write-Host "==> Keeping existing $SecretsJson"
}}

$scriptsDir = python -c "import os, sysconfig; print(sysconfig.get_path('scripts', f'{{os.name}}_user') or '')" 2>$null
if (-not $scriptsDir) {{
  $userBase = python -m site --user-base 2>$null
  $scriptsDir = if ($userBase) {{ Join-Path $userBase "Scripts" }} else {{ $null }}
}}
if ($scriptsDir -and (Test-Path $scriptsDir)) {{
  $pathParts = @($env:Path -split ';' | Where-Object {{ $_ }})
  if ($pathParts -notcontains $scriptsDir) {{
    $env:Path = "$scriptsDir;$env:Path"
  }}

  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $userPathParts = @($userPath -split ';' | Where-Object {{ $_ }})
  if ($userPathParts -notcontains $scriptsDir) {{
    $newUserPath = if ($userPath) {{ "$scriptsDir;$userPath" }} else {{ $scriptsDir }}
    [Environment]::SetEnvironmentVariable("Path", $newUserPath, [EnvironmentVariableTarget]::User)
    Write-Host "==> Added STRATA Scripts dir to user PATH: $scriptsDir"
  }}

  $profileMarker = "# STRATA_PATH_BLOCK_BEGIN"
  $profileEndMarker = "# STRATA_PATH_BLOCK_END"
  if ($PROFILE) {{
    $profileDir = Split-Path $PROFILE -Parent
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
    $profileContent = if (Test-Path $PROFILE) {{ Get-Content $PROFILE -Raw }} else {{ "" }}
    if ($profileContent -notlike "*$profileMarker*") {{
      Add-Content -Path $PROFILE -Value @"

$profileMarker
# STRATA pip user Scripts
`$__strataScripts = python -c "import os, sysconfig; print(sysconfig.get_path('scripts', f'{{os.name}}_user') or '')" 2>`$null
if (`$__strataScripts -and (Test-Path `$__strataScripts)) {{ `$env:Path = "`$__strataScripts;" + `$env:Path }}
$profileEndMarker
"@
      Write-Host "==> Added STRATA Scripts dir to PowerShell profile: $PROFILE"
    }}
  }}
  Write-Host "==> PATH includes $scriptsDir for this session"
}}

function Invoke-Strata {{
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  if (Get-Command strata -ErrorAction SilentlyContinue) {{
    & strata @Args
  }} else {{
    & python -m cxl_strata.cli @Args
  }}
}}

if ($Init) {{
  $initArgs = @("init", "--api", $ApiUrl, "--org", $Org)
  if ($Project) {{ $initArgs += @("--project", $Project) }}
  if ($Repo) {{ $initArgs += @("--repo", $Repo) }}
  if ($ActorName) {{ $initArgs += @("--actor-name", $ActorName) }}
  if ($ActorEmail) {{ $initArgs += @("--actor-email", $ActorEmail) }}
  Write-Host "==> Running strata $($initArgs -join ' ')"
  Invoke-Strata @initArgs
  $indexArgs = @("index")
  Write-Host "==> Initializing STRATA local SQLite index"
  try {{
    Invoke-Strata @indexArgs
  }} catch {{
    Write-Warning "Local SQLite index initialization failed; run: python -m cxl_strata.cli index"
  }}
  $appArgs = @("app", "--open")
  Write-Host "==> Opening STRATA localhost UI"
  Invoke-Strata @appArgs
}}

if ($Cursor) {{
  Write-Host @"

==> Cursor MCP snippet (%USERPROFILE%\\.cursor\\mcp.json):

{{
  `"mcpServers`": {{
    `"strata`": {{
      `"command`": `"python`",
      `"args`": [`"-m`", `"strata_mcp.server`"],
      `"env`": {{
        `"STRATA_API_URL`": `"$ApiUrl`",
        `"STRATA_API_KEY`": `"strata_live_YOUR_TOKEN`"
      }}
    }}
  }}
}}
"@
}}

Write-Host @"

STRATA client installed.

Next steps:
  1. Edit $SecretsJson and set api_key to your strata_live_... token
  2. If this shell has the latest CLI, run the post-key bootstrap:
     python -m cxl_strata.cli --init
     This hardens PATH, creates .md\\workspace_index.sqlite, and opens the local UI.
  3. If --init says 'No such option', use the installer bootstrap instead:
     & ([scriptblock]::Create((irm {public_url}/install.ps1))) -Org $Org -Init
  4. Verify (this session): Invoke-Strata whoami
     Or after opening a new terminal: strata whoami
  5. Init this workspace (pass switches to the scriptblock, NOT to iex):
     & ([scriptblock]::Create((irm {public_url}/install.ps1))) -Org craftxlogic -Init
  6. -Init initializes SQLite and installs .cursor\\skills\\strata\\SKILL.md when a Cursor workspace is detected
  7. Refresh local index later with: strata index
  8. Open UI: strata app --open
  9. Optional autostart: strata app install-autostart
  10. Optional MCP snippet:
     & ([scriptblock]::Create((irm {public_url}/install.ps1))) -Cursor

Quick test now: python -m cxl_strata.cli whoami

Manifest: {public_url}/v1/client/manifest
"@
"""


def render_install_sh() -> str:
    return INSTALL_SH.format(
        public_url=settings.strata_public_url.rstrip("/"),
        git_url=settings.strata_client_git_url,
        git_ref=settings.strata_client_git_ref,
        default_org=settings.strata_default_org,
    )


def render_install_ps1() -> str:
    return INSTALL_PS1.format(
        public_url=settings.strata_public_url.rstrip("/"),
        git_url=settings.strata_client_git_url,
        git_ref=settings.strata_client_git_ref,
        default_org=settings.strata_default_org,
    )


def client_manifest() -> dict:
    base = settings.strata_public_url.rstrip("/")
    git_ref = settings.strata_client_git_ref
    git_url = settings.strata_client_git_url
    cli_spec = f"git+{git_url}@{git_ref}#subdirectory=cli"
    mcp_spec = f"git+{git_url}@{git_ref}#subdirectory=mcp"
    return {
        "api": "strata",
        "version": settings.strata_client_version,
        "public_url": base,
        "default_org": settings.strata_default_org,
        "install": {
            "unix_one_liner": f"curl -fsSL {base}/install.sh | bash",
            "unix_with_init": (
                f"curl -fsSL {base}/install.sh | bash -s -- --org {settings.strata_default_org} --init"
            ),
            "unix_update": f"curl -fsSL {base}/install.sh | bash",
            "windows_one_liner": f"irm {base}/install.ps1 | iex",
            "windows_with_init": (
                f"& ([scriptblock]::Create((irm {base}/install.ps1))) "
                f"-Org {settings.strata_default_org} -Init"
            ),
            "windows_update": (
                f"& ([scriptblock]::Create((irm {base}/install.ps1))) "
                f"-Org {settings.strata_default_org}"
            ),
            "windows_with_cursor": (
                f"& ([scriptblock]::Create((irm {base}/install.ps1))) -Cursor"
            ),
        },
        "packages": {
            "cli": {"pip_spec": cli_spec, "command": "strata"},
            "mcp": {"pip_spec": mcp_spec, "module": "strata_mcp.server"},
        },
        "config": {
            "user_global": "~/.strata/global.json",
            "user_secrets": "~/.strata/secrets.json",
            "repo_config": ".strata/config.json",
            "env_api_key": "STRATA_API_KEY",
        },
        "requirements": {
            "python_cli": ">=3.10",
            "python_mcp": ">=3.11",
            "git": "required for pip install from git until PyPI publish",
        },
        "workspace_knowledge": {
            "index": "strata index",
            "prune": "strata prune --archive-handoffs",
            "prune_project": "strata prune YOUR_PROJECT --archive-handoffs",
            "prune_execute": "strata prune --archive-handoffs --execute",
            "prune_project_execute": "strata prune YOUR_PROJECT --archive-handoffs --execute",
            "stash": "strata stash",
            "stash_project": "strata stash --project YOUR_PROJECT",
            "pull": "strata pull",
            "app": "strata app --open",
            "autostart": "strata app install-autostart",
            "cursor_skill": ".cursor/skills/strata/SKILL.md",
            "cursor_rule": ".cursor/rules/strata-memory-capture.mdc",
            "post_key_bootstrap": "python -m cxl_strata.cli --init",
            "post_key_bootstrap_fallback_windows": (
                f"& ([scriptblock]::Create((irm {base}/install.ps1))) "
                f"-Org {settings.strata_default_org} -Init"
            ),
            "local_db": ".md/workspace_index.sqlite",
            "ui_port": 8765,
        },
    }
