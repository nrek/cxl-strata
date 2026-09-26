#!/usr/bin/env bash
set -euo pipefail

# In-place production update for the existing checkout at /var/www/cxl-strata.
# Matches the host procedure used since 2026-07: git pull, api/.venv, api/.env,
# alembic, restart cxl-strata-api, reload Apache. Does not create releases,
# move the app root, or rewrite the systemd unit.
#
# A dirty tree blocks git pull when tracked files differ or untracked files
# sit on paths the incoming commit adds. This script saves that state under
# backups/ and then checks out origin. Ignored files (api/.env, api/.venv)
# are left in place.
#
#   cd /var/www/cxl-strata
#   ./deploy.sh deploy

APP_ROOT="${APP_ROOT:-/var/www/cxl-strata}"
BRANCH="${BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
SERVICE_NAME="${SERVICE_NAME:-cxl-strata-api}"
APP_ROOT="${APP_ROOT//$'\r'/}"
BRANCH="${BRANCH//$'\r'/}"
REMOTE="${REMOTE//$'\r'/}"
SERVICE_NAME="${SERVICE_NAME//$'\r'/}"
PORT="${PORT:-8015}"
HEALTH_CHECK_RETRIES="${HEALTH_CHECK_RETRIES:-12}"
HEALTH_CHECK_INTERVAL_SECONDS="${HEALTH_CHECK_INTERVAL_SECONDS:-2}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

require_checkout() {
  git -C "$APP_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "git cannot read the checkout at $APP_ROOT (.git is there; run as ubuntu: sudo -u ubuntu ./deploy.sh deploy)"
  [ -d "$APP_ROOT/api/.venv" ] || fail "Missing $APP_ROOT/api/.venv"
  [ -f "$APP_ROOT/api/.env" ] || fail "Missing $APP_ROOT/api/.env"
}

save_dirty_state() {
  local backup status_file
  backup="$APP_ROOT/backups/pre-deploy-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup"
  git -C "$APP_ROOT" status --short > "$backup/status.txt" || true
  git -C "$APP_ROOT" diff > "$backup/tracked.diff" || true
  status_file="$backup/status.txt"
  if [ ! -s "$status_file" ]; then
    log "Working tree is clean"
    rmdir "$backup" 2>/dev/null || true
    return 0
  fi
  log "Saved working tree state to $backup"
  cat "$status_file"
}

# Untracked files that origin already contains block checkout. Move only those.
move_conflicting_untracked() {
  local backup path target
  backup="$APP_ROOT/backups/untracked-$(date +%Y%m%d-%H%M%S)"
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if git -C "$APP_ROOT" cat-file -e "$REMOTE/$BRANCH:$path" 2>/dev/null; then
      mkdir -p "$backup/$(dirname "$path")"
      target="$backup/$path"
      log "Moving untracked $path aside (origin/$BRANCH already has this path)"
      mv "$APP_ROOT/$path" "$target"
    fi
  done < <(git -C "$APP_ROOT" ls-files -o --exclude-standard)
}

sync_origin() {
  log "Fetching $REMOTE $BRANCH"
  git -C "$APP_ROOT" fetch "$REMOTE" "$BRANCH"
  move_conflicting_untracked
  log "Checking out $REMOTE/$BRANCH"
  git -C "$APP_ROOT" reset --hard "$REMOTE/$BRANCH"
}

install_and_migrate() {
  log "Installing API requirements and applying migrations"
  (
    cd "$APP_ROOT/api"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    pip install -r requirements.txt
    alembic upgrade head
    python -m pytest tests -q
  )
}

restart_services() {
  log "Restarting $SERVICE_NAME"
  run_sudo systemctl restart "$SERVICE_NAME"
  if command -v apache2ctl >/dev/null 2>&1; then
    run_sudo apache2ctl configtest
    run_sudo systemctl reload apache2 || run_sudo systemctl restart apache2
  fi
}

wait_for_health() {
  local attempt code
  for attempt in $(seq 1 "$HEALTH_CHECK_RETRIES"); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${PORT}/health" || true)"
    if [ "$code" = "200" ]; then
      log "Health returned HTTP 200"
      return 0
    fi
    log "Health not ready (HTTP ${code:-000}, attempt $attempt/$HEALTH_CHECK_RETRIES)"
    sleep "$HEALTH_CHECK_INTERVAL_SECONDS"
  done
  run_sudo systemctl status "$SERVICE_NAME" --no-pager || true
  fail "http://127.0.0.1:${PORT}/health did not return HTTP 200"
}

deploy() {
  require_checkout
  save_dirty_state
  sync_origin
  install_and_migrate
  restart_services
  wait_for_health
  log "Deployment completed at $APP_ROOT ($(git -C "$APP_ROOT" rev-parse --short HEAD))"
}

status() {
  git -C "$APP_ROOT" status --short || true
  git -C "$APP_ROOT" log -1 --oneline || true
  run_sudo systemctl status "$SERVICE_NAME" --no-pager || true
  curl -sS -o /dev/null -w "health HTTP %{http_code}\n" --max-time 3 "http://127.0.0.1:${PORT}/health" || true
}

usage() {
  cat <<EOF
Usage: $0 {deploy|status}

APP_ROOT=$APP_ROOT
BRANCH=$BRANCH
SERVICE_NAME=$SERVICE_NAME
EOF
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    deploy) deploy ;;
    status) status ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
