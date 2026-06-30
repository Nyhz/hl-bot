#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
set -euo pipefail

# Controla el despliegue completo como UNA unidad: bot (API :3300) + dashboard (:3400).
# Nunca se opera uno sin el otro: start/stop/restart actúan sobre ambos.
BOT_LABEL="com.hlbot.app"
DASH_LABEL="com.hldash.app"
GUI_DOMAIN="gui/$(id -u)"

REPO="$HOME/dev/hl-bot/bot"
DASHDIR="$HOME/dev/hl-bot/dashboard"
PY="$REPO/.venv/bin/python"
NODE="$(command -v node)"
NODEBIN="$(dirname "$NODE")"
DASH_PORT=3400

STATE_DIR="$HOME/.hlbot"
MODE_FILE="$STATE_DIR/mode"
LOG_DIR="$STATE_DIR/logs"
BOT_LOG="$LOG_DIR/hlbot.log"
DASH_LOG="$LOG_DIR/hldash.log"

BOT_PLIST_SRC="$REPO/scripts/com.hlbot.app.plist"
DASH_PLIST_SRC="$REPO/scripts/com.hldash.app.plist"
BOT_PLIST_DST="$HOME/Library/LaunchAgents/${BOT_LABEL}.plist"
DASH_PLIST_DST="$HOME/Library/LaunchAgents/${DASH_LABEL}.plist"

mkdir -p "$STATE_DIR" "$LOG_DIR"
[ -f "$MODE_FILE" ] || echo "dev" > "$MODE_FILE"

build_dashboard() {
  echo "compilando dashboard…"
  ( cd "$DASHDIR" && npm run build )
  echo "dashboard compilado"
}

install_all() {
  mkdir -p "$HOME/Library/LaunchAgents"
  # Bot
  sed "s#__PY__#${PY}#g; s#__REPO__#${REPO}#g; s#__LOG__#${BOT_LOG}#g" \
    "$BOT_PLIST_SRC" > "$BOT_PLIST_DST"
  # Dashboard (requiere build previo para 'next start')
  [ -d "$DASHDIR/.next" ] || build_dashboard
  sed "s#__NODE__#${NODE}#g; s#__NODEBIN__#${NODEBIN}#g; s#__DASHDIR__#${DASHDIR}#g; s#__PORT__#${DASH_PORT}#g; s#__LOG__#${DASH_LOG}#g" \
    "$DASH_PLIST_SRC" > "$DASH_PLIST_DST"
  for L in "$BOT_LABEL" "$DASH_LABEL"; do
    launchctl bootout "${GUI_DOMAIN}/${L}" 2>/dev/null || true
  done
  launchctl bootstrap "$GUI_DOMAIN" "$BOT_PLIST_DST"
  launchctl bootstrap "$GUI_DOMAIN" "$DASH_PLIST_DST"
  echo "instalados ${BOT_LABEL} + ${DASH_LABEL}"
}

start_all()   { for L in "$BOT_LABEL" "$DASH_LABEL"; do launchctl kickstart -k "${GUI_DOMAIN}/${L}" 2>/dev/null || true; done; }
stop_all()    { for L in "$BOT_LABEL" "$DASH_LABEL"; do launchctl bootout "${GUI_DOMAIN}/${L}" 2>/dev/null || true; done; }
restart_all() { start_all; }

case "${1:-}" in
  start)   start_all ;;
  stop)    stop_all ;;
  restart) restart_all ;;
  # dev/prod = testnet/mainnet del bot; el dashboard es agnóstico (lo refleja solo).
  dev)     echo "dev"  > "$MODE_FILE"; launchctl kickstart -k "${GUI_DOMAIN}/${BOT_LABEL}" 2>/dev/null || true ;;
  prod)    echo "prod" > "$MODE_FILE"; launchctl kickstart -k "${GUI_DOMAIN}/${BOT_LABEL}" 2>/dev/null || true ;;
  build)   build_dashboard; launchctl kickstart -k "${GUI_DOMAIN}/${DASH_LABEL}" 2>/dev/null || true ;;
  install) install_all ;;
  *) echo "uso: $0 {start|stop|restart|dev|prod|build|install}" >&2; exit 2 ;;
esac
