#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LABEL="com.hlbot.app"
GUI_DOMAIN="gui/$(id -u)"
XRUN="$HOME/dev/hl-bot/bot/scripts/hlbot-xbar-run.sh"
DB_FILE="$HOME/dev/hl-bot/bot/data.db"
MODE_FILE="$HOME/.hlbot/mode"
LOG_FILE="$HOME/.hlbot/logs/hlbot.log"
PORT=3300

MODE="dev"; [ -f "$MODE_FILE" ] && MODE="$(cat "$MODE_FILE" 2>/dev/null)"
[ "$MODE" = "prod" ] && NET="MAINNET" || NET="TESTNET"

# Servicio
PID="$(launchctl print "${GUI_DOMAIN}/${LABEL}" 2>/dev/null | awk '/pid =/{print $3; exit}')"
RUNNING=false; [ -n "$PID" ] && RUNNING=true

# Health HTTP
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 3 "http://localhost:${PORT}/state" 2>/dev/null)"
HEALTHY=false; { [ "$HTTP_CODE" -ge 200 ] 2>/dev/null && [ "$HTTP_CODE" -lt 500 ] 2>/dev/null; } && HEALTHY=true

# Estado -> glifo + color (mainnet en ámbar para que cante)
if $RUNNING && $HEALTHY; then
  if [ "$MODE" = "prod" ]; then echo "● HL | color=#ffaa00 size=13"; else echo "● HL | color=#00ff00 size=13"; fi
elif $RUNNING; then echo "● HL | color=#ffaa00 size=13"
else echo "○ HL | color=#ff4444 size=13"; fi

echo "---"
echo "Estado: $($RUNNING && echo corriendo || echo parado) | color=white"
echo "Modo: $NET | color=$([ "$MODE" = prod ] && echo '#ffaa00' || echo '#888888')"
[ -n "$PID" ] && echo "PID: $PID | color=#888888"
echo "Puerto: $PORT | color=#888888"

# Digest en vivo (SQLite read-only): última sesión + posiciones/PnL/fees
if [ -f "$DB_FILE" ]; then
  echo "---"
  SID="$(sqlite3 -readonly "$DB_FILE" "SELECT id FROM sessions ORDER BY id DESC LIMIT 1;" 2>/dev/null)"
  if [ -n "$SID" ]; then
    NFILLS="$(sqlite3 -readonly "$DB_FILE" "SELECT COUNT(*) FROM fills WHERE session_id=$SID;" 2>/dev/null)"
    FEES="$(sqlite3 -readonly "$DB_FILE" "SELECT printf('%.4f', COALESCE(SUM(fee),0)) FROM fills WHERE session_id=$SID;" 2>/dev/null)"
    PNL="$(sqlite3 -readonly "$DB_FILE" "SELECT printf('%.2f', total_pnl) FROM pnl_snapshots WHERE session_id=$SID ORDER BY id DESC LIMIT 1;" 2>/dev/null)"
    echo "Sesión #$SID | color=white"
    echo "Fills: ${NFILLS:-0} | color=#888888"
    echo "PnL: ${PNL:-n/d} | color=$([ -n "$PNL" ] && echo '#888888' || echo '#888888')"
    echo "Fees: ${FEES:-0} | color=#888888"
  else
    echo "Sin sesiones aún | color=#888888"
  fi
fi

# Acciones (ciclo de vida)
echo "---"
if $RUNNING; then
  if [ "$MODE" = "dev" ]; then
    echo "Switch to Prod (MAINNET) | bash=$XRUN param1=prod terminal=false refresh=true"
  else
    echo "Switch to Dev (TESTNET) | bash=$XRUN param1=dev terminal=false refresh=true"
  fi
  echo "Restart | bash=$XRUN param1=restart terminal=false refresh=true"
  echo "Stop | bash=$XRUN param1=stop terminal=false refresh=true"
else
  echo "Start | bash=$XRUN param1=start terminal=false refresh=true"
fi

# Caddy + enlaces
echo "---"
CADDY="$(brew services info caddy 2>/dev/null | grep -q 'started' && echo '✓ Caddy' || echo '✗ Caddy')"
echo "$CADDY | color=#888888"
echo "Open dashboard | href=http://localhost:${PORT}"
echo "View Logs | bash=/usr/bin/open param1=-a param2=Terminal param3=$LOG_FILE terminal=false"
