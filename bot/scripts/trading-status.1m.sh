#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

BOT_LABEL="com.hlbot.app"
DASH_LABEL="com.hldash.app"
GUI_DOMAIN="gui/$(id -u)"
XRUN="$HOME/dev/hl-bot/bot/scripts/hlbot-xbar-run.sh"
DB_FILE="$HOME/dev/hl-bot/bot/data.db"
MODE_FILE="$HOME/.hlbot/mode"
BOT_LOG="$HOME/.hlbot/logs/hlbot.log"
DASH_LOG="$HOME/.hlbot/logs/hldash.log"
BOT_PORT=3300
DASH_PORT=3400
DASH_URL="https://trading.lan"

MODE="dev"; [ -f "$MODE_FILE" ] && MODE="$(cat "$MODE_FILE" 2>/dev/null)"
[ "$MODE" = "prod" ] && NET="MAINNET" || NET="TESTNET"

svc_pid() { launchctl print "${GUI_DOMAIN}/$1" 2>/dev/null | awk '/pid =/ && $3 ~ /^[0-9]+$/ {print $3; exit}'; }
http_ok() { # $1 = url
  local code; code="$(curl -sk -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 3 "$1" 2>/dev/null)"
  [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 500 ] 2>/dev/null
}

BOT_PID="$(svc_pid "$BOT_LABEL")"
DASH_PID="$(svc_pid "$DASH_LABEL")"
BOT_UP=false; { [ -n "$BOT_PID" ] && http_ok "http://localhost:${BOT_PORT}/state"; } && BOT_UP=true
DASH_UP=false; { [ -n "$DASH_PID" ] && http_ok "http://localhost:${DASH_PORT}/"; } && DASH_UP=true

# Glifo combinado: ambos arriba => verde(mainnet)/naranja(testnet); uno caído => ámbar aviso; ambos abajo => rojo.
if $BOT_UP && $DASH_UP; then
  if [ "$MODE" = "prod" ]; then echo "● HL | color=#00ff00 size=13"; else echo "● HL | color=#ffaa00 size=13"; fi
elif $BOT_UP || $DASH_UP; then
  echo "◐ HL | color=#ffcc00 size=13"
else
  echo "○ HL | color=#ff4444 size=13"
fi

echo "---"
echo "Modo: $NET | color=$([ "$MODE" = prod ] && echo '#00ff00' || echo '#ffaa00')"
echo "Bot (API :$BOT_PORT): $($BOT_UP && echo '✓ activo' || echo '✗ caído') | color=$($BOT_UP && echo '#00ff00' || echo '#ff4444')"
[ -n "$BOT_PID" ] && echo "  pid $BOT_PID | color=#888888"
echo "Dashboard (:$DASH_PORT): $($DASH_UP && echo '✓ activo' || echo '✗ caído') | color=$($DASH_UP && echo '#00ff00' || echo '#ff4444')"
[ -n "$DASH_PID" ] && echo "  pid $DASH_PID | color=#888888"

# Digest en vivo (SQLite read-only): última sesión + fills/PnL/fees
if [ -f "$DB_FILE" ]; then
  echo "---"
  SID="$(sqlite3 -readonly "$DB_FILE" "SELECT id FROM sessions ORDER BY id DESC LIMIT 1;" 2>/dev/null)"
  if [ -n "$SID" ]; then
    NFILLS="$(sqlite3 -readonly "$DB_FILE" "SELECT COUNT(*) FROM fills WHERE session_id=$SID;" 2>/dev/null)"
    FEES="$(sqlite3 -readonly "$DB_FILE" "SELECT printf('%.4f', COALESCE(SUM(fee),0)) FROM fills WHERE session_id=$SID;" 2>/dev/null)"
    PNL="$(sqlite3 -readonly "$DB_FILE" "SELECT printf('%.2f', total_pnl) FROM pnl_snapshots WHERE session_id=$SID ORDER BY id DESC LIMIT 1;" 2>/dev/null)"
    echo "Sesión #$SID | color=white"
    echo "Fills: ${NFILLS:-0} | color=#888888"
    PNL_COLOR="#888888"
    if [ -n "$PNL" ]; then
      case "$(echo "$PNL" | cut -c1)" in
        -) PNL_COLOR="#ff4444" ;;
        *) PNL_COLOR="#00ff00" ;;
      esac
    fi
    echo "PnL: ${PNL:-n/d} | color=$PNL_COLOR"
    echo "Fees: ${FEES:-0} | color=#888888"
  else
    echo "Sin sesiones aún | color=#888888"
  fi
fi

# Acciones (ciclo de vida) — actúan sobre AMBOS servicios a la vez
echo "---"
if $BOT_UP || $DASH_UP; then
  echo "Stop (bot + dashboard) | bash=$XRUN param1=stop terminal=false refresh=true"
  echo "Restart (bot + dashboard) | bash=$XRUN param1=restart terminal=false refresh=true"
else
  echo "Start (bot + dashboard) | bash=$XRUN param1=start terminal=false refresh=true"
fi
if [ "$MODE" = "dev" ]; then
  echo "Switch to Prod (MAINNET) | bash=$XRUN param1=prod terminal=false refresh=true"
else
  echo "Switch to Dev (TESTNET) | bash=$XRUN param1=dev terminal=false refresh=true"
fi
echo "Rebuild dashboard | bash=$XRUN param1=build terminal=false refresh=true"

# Enlaces
echo "---"
echo "Open dashboard | href=$DASH_URL"
echo "View bot logs | bash=/usr/bin/open param1=-a param2=Terminal param3=$BOT_LOG terminal=false"
echo "View dashboard logs | bash=/usr/bin/open param1=-a param2=Terminal param3=$DASH_LOG terminal=false"
