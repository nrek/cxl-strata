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
  --project SLUG      Project slug for strata init (requires --init)
  --repo NAME         Repo name for strata init (default: basename of cwd)
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

PIP=(python3 -m pip install --user --upgrade)
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

# Ensure user-local bin is on PATH for this session
USER_BASE="$(python3 -m site --user-base 2>/dev/null || echo "$HOME/.local")"
export PATH="$USER_BASE/bin:$PATH"

if [[ "$DO_INIT" -eq 1 ]]; then
  if ! command -v strata >/dev/null 2>&1; then
    echo "strata CLI not on PATH. Add to your shell profile:" >&2
    echo "  export PATH=\\"$(python3 -m site --user-base)/bin:\\$PATH\\"" >&2
    exit 1
  fi
  REPO="${{REPO:-$(basename "$(pwd)")}}"
  PROJECT="${{PROJECT:-$REPO}}"
  INIT_ARGS=(init --api "$STRATA_API_URL" --org "$STRATA_ORG" --project "$PROJECT" --repo "$REPO")
  [[ -n "$ACTOR_NAME" ]] && INIT_ARGS+=(--actor-name "$ACTOR_NAME")
  [[ -n "$ACTOR_EMAIL" ]] && INIT_ARGS+=(--actor-email "$ACTOR_EMAIL")
  echo "==> Running strata ${{INIT_ARGS[*]}}"
  strata "${{INIT_ARGS[@]}}"
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
  2. In each repo: curl -fsSL {public_url}/install.sh | bash -s -- --init --project YOUR_PROJECT
     — or: strata init --api ${{STRATA_API_URL}} --org ${{STRATA_ORG}} --project SLUG --repo NAME
  3. Verify: strata whoami
  4. Optional Cursor MCP: re-run with --cursor for JSON snippet

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
python -m pip install --user --upgrade $CliSpec
Write-Host "==> Installing STRATA MCP server"
python -m pip install --user --upgrade $McpSpec

$StrataHome = Join-Path $env:USERPROFILE ".strata"
New-Item -ItemType Directory -Force -Path $StrataHome | Out-Null

$GlobalJson = Join-Path $StrataHome "global.json"
if (-not (Test-Path $GlobalJson)) {{
  @{{ api_base_url = $ApiUrl; organization_slug = $Org; installed_from = "{public_url}/install.ps1" }} |
    ConvertTo-Json | Set-Content -Encoding utf8 $GlobalJson
  Write-Host "==> Wrote $GlobalJson"
}} else {{
  Write-Host "==> Keeping existing $GlobalJson"
}}

$SecretsJson = Join-Path $StrataHome "secrets.json"
if (-not (Test-Path $SecretsJson)) {{
  '{{"api_key":"REPLACE_WITH_strata_live_OR_strata_dev_TOKEN"}}' | Set-Content -Encoding utf8 $SecretsJson
  Write-Host "==> Wrote $SecretsJson — edit api_key before syncing"
}} else {{
  Write-Host "==> Keeping existing $SecretsJson"
}}

$userBase = python -m site --user-base 2>$null
if ($userBase) {{ $env:Path = "$userBase\\Scripts;$userBase;$env:Path" }}

if ($Init) {{
  Require-Command strata
  if (-not $Repo) {{ $Repo = Split-Path -Leaf (Get-Location) }}
  if (-not $Project) {{ $Project = $Repo }}
  $initArgs = @("init", "--api", $ApiUrl, "--org", $Org, "--project", $Project, "--repo", $Repo)
  if ($ActorName) {{ $initArgs += @("--actor-name", $ActorName) }}
  if ($ActorEmail) {{ $initArgs += @("--actor-email", $ActorEmail) }}
  Write-Host "==> Running strata $($initArgs -join ' ')"
  & strata @initArgs
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
  2. Per repo: irm {public_url}/install.ps1 | iex; then run with -Init -Project YOUR_PROJECT
  3. Verify: strata whoami
  4. Optional: re-run with -Cursor for MCP JSON

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
        "version": "0.2.0",
        "public_url": base,
        "default_org": settings.strata_default_org,
        "install": {
            "unix_one_liner": f"curl -fsSL {base}/install.sh | bash",
            "unix_with_init": (
                f"curl -fsSL {base}/install.sh | bash -s -- --org {settings.strata_default_org} --init"
            ),
            "windows_one_liner": f"irm {base}/install.ps1 | iex",
            "windows_with_init": (
                f"irm {base}/install.ps1 | iex; "
                f"irm {base}/install.ps1 | iex -Org {settings.strata_default_org} -Init"
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
    }
