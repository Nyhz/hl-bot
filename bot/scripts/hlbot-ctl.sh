#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
set -euo pipefail

LABEL="com.hlbot.app"
GUI_DOMAIN="gui/$(id -u)"
REPO="$HOME/dev/hl-bot/bot"
PY="$REPO/.venv/bin/python"
STATE_DIR="$HOME/.hlbot"
MODE_FILE="$STATE_DIR/mode"
LOG_DIR="$STATE_DIR/logs"
LOG_FILE="$LOG_DIR/hlbot.log"
PLIST_SRC="$REPO/scripts/com.hlbot.app.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$STATE_DIR" "$LOG_DIR"
[ -f "$MODE_FILE" ] || echo "dev" > "$MODE_FILE"

install_plist() {
  mkdir -p "$HOME/Library/LaunchAgents"
  sed "s#__PY__#${PY}#g; s#__REPO__#${REPO}#g; s#__LOG__#${LOG_FILE}#g" \
    "$PLIST_SRC" > "$PLIST_DST"
  launchctl bootout "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true
  launchctl bootstrap "$GUI_DOMAIN" "$PLIST_DST"
  echo "instalado ${LABEL}"
}

case "${1:-}" in
  start)   launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" ;;
  stop)    launchctl bootout "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true ;;
  restart) launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" ;;
  dev)     echo "dev"  > "$MODE_FILE"; launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true ;;
  prod)    echo "prod" > "$MODE_FILE"; launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true ;;
  install) install_plist ;;
  *) echo "uso: $0 {start|stop|restart|dev|prod|install}" >&2; exit 2 ;;
esac
