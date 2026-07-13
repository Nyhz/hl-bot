---
name: verify
description: Cómo arrancar y verificar el bot hl-bot end-to-end contra testnet (API :3300, sesiones, crash-recovery)
---

# Verificar hl-bot en vivo (testnet)

## Arrancar el bot a mano (sin launchd)

```bash
cd bot && PYTHONPATH=src .venv/bin/python -m hlbot.main > /tmp/bot.log 2>&1 &
```

- Puerto: `127.0.0.1:3300`. Comprobar que está libre antes (`lsof -i :3300`).
- El modo (testnet/mainnet) sale de `~/.hlbot/mode` (`dev`/`prod`); credenciales de `bot/.env`.
- Si los servicios launchd están cargados (`com.hlbot.app`), pararlos primero o chocará el puerto.
- OJO cwd: cada llamada Bash puede resetear el working dir — usar rutas absolutas en
  comandos posteriores o `sqlite3` creará un `data.db` vacío donde no toca (la BD real
  es `bot/data.db`).

## Driving básico

```bash
curl -s http://127.0.0.1:3300/state | python -c "..."   # state/session_id/mode/coins
TOKEN=$(grep CONTROL_TOKEN bot/.env | cut -d= -f2)       # NUNCA imprimir el token
# lanzar sesión mínima (grid_n*10 <= capital):
curl -X POST :3300/session/launch -H "X-Control-Token: $TOKEN" -d '{"watchlist":["BTC"],
  "capital":40,"grid_n":2,"limits":{"max_position_notional":10,"max_open_positions":2,
  "max_leverage":2,"daily_loss_limit":5,"total_loss_limit":10,"max_coin_notional":30}}'
curl -X POST :3300/session/kill -H ... -d '{"confirm":true}'   # limpia todo de verdad
```

- Tick = 5s; dar ~10-12s tras launch para ver órdenes colocadas (state pasa a `active`).
- Verdad del exchange (read-only, sin credenciales): SDK `Info(TESTNET_API_URL)` →
  `open_orders(addr)` (reposo; los stops trigger SOLO en `frontend_open_orders`),
  `user_state(addr)` (posiciones).
- Runtime persistido: `sqlite3 bot/data.db "SELECT * FROM session_runtime"`.

## Simulacro de crash-recovery (verificado 2026-07-13)

1. launch sesión → esperar ticks → `pkill -9 -f hlbot.main`
2. rearrancar → `/state` debe traer el MISMO session_id, log `[startup] sesion N rehidratada`,
   risk_event `rehydrate` en BD, y la escalera sigue/vuelve al exchange.
3. kill de sesión por API → rearrancar → arranque limpio SILENCIOSO (0 líneas `[startup]`).

## Limpieza al terminar

`pkill -9 -f hlbot.main` + comprobar reposo=0/posiciones=0 en el exchange + recordar
que el despliegue real es launchd: `bash bot/scripts/hlbot-ctl.sh install` (solo funciona
desde la sesión GUI del usuario, no desde el sandbox).
