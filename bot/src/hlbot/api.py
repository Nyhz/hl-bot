from __future__ import annotations
import asyncio
import hmac
import os
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from hlbot.models import SessionConfig, RiskLimits
from hlbot.session_engine import SessionEngine
from hlbot.account import merge_tape, format_candles
from hlbot.track_record import session_summary, global_stats

LIQUID_MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
MAX_OPEN_CAP = 4  # tope duro de posiciones simultaneas, no editable


class LimitsBody(BaseModel):
    max_position_notional: float
    max_open_positions: int
    max_leverage: float
    daily_loss_limit: float
    total_loss_limit: float
    max_coin_notional: float = 30.0


class LaunchBody(BaseModel):
    watchlist: list[str]
    capital: float
    limits: LimitsBody
    grid_n: int = 10
    grid_range_pct: float = 0.02
    adx_threshold: float = 25.0


class KillBody(BaseModel):
    confirm: bool


def create_app(engine: SessionEngine, control_token: str,
               market_state_provider, account_provider=lambda: {}) -> FastAPI:
    app = FastAPI(title="hlbot")
    origin = os.getenv("DASHBOARD_ORIGIN", "http://localhost:3000")
    app.add_middleware(
        CORSMiddleware, allow_origins=[origin], allow_methods=["*"],
        allow_headers=["*"],
    )

    def _auth(token: str | None):
        if token is None or not hmac.compare_digest(token, control_token):
            raise HTTPException(status_code=401, detail="token de control invalido")

    def _full_snapshot():
        snap = engine.snapshot(market_state_provider())
        acc = dict(account_provider())
        fills = acc.pop("_fills", [])
        acc.pop("_funding", None)
        decisions = engine.store.get_decisions(engine.session_id) if engine.session_id else []
        snap["account"] = acc
        snap["positions"] = acc.get("positions", [])
        snap["tape_recent"] = merge_tape(decisions, fills, limit=20)
        return snap

    @app.get("/state")
    def state():
        return _full_snapshot()

    @app.get("/history")
    def history():
        if engine.session_id is None:
            return {"decisions": []}
        return {"decisions": engine.store.get_decisions(engine.session_id)}

    @app.post("/session/launch")
    def launch(body: LaunchBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        limits_data = body.limits.model_dump()
        limits_data["max_open_positions"] = min(MAX_OPEN_CAP, limits_data["max_open_positions"])
        limits = RiskLimits(**limits_data)
        cfg = SessionConfig(watchlist=body.watchlist, capital=body.capital,
                            limits=limits, grid_n=body.grid_n,
                            grid_range_pct=body.grid_range_pct,
                            adx_threshold=body.adx_threshold)
        try:
            engine.launch(cfg)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"state": engine.state.value}

    @app.post("/session/close")
    def close(x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        try:
            engine.close()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"state": engine.state.value}

    @app.post("/session/kill")
    def kill(body: KillBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        try:
            engine.kill(confirm=body.confirm)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"state": engine.state.value}

    @app.post("/limits")
    def update_limits(body: LimitsBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        if engine.risk is None:
            raise HTTPException(status_code=409, detail="no hay sesion activa")
        engine.risk.limits = RiskLimits(**body.model_dump())
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(_full_snapshot())
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    @app.get("/account")
    def account():
        a = dict(account_provider())
        a.pop("_fills", None); a.pop("_funding", None)
        return a

    @app.get("/positions")
    def positions():
        return account_provider().get("positions", [])

    @app.get("/equity_curve")
    def equity_curve(session_id: int):
        return engine.store.get_pnl_snapshots(session_id)

    @app.get("/candles/{coin}")
    def candles(coin: str, interval: str = "1m", limit: int = 500):
        raw = engine.store.get_candles(coin, interval, limit)
        norm = [{"t": r["t"], "o": r["open"], "h": r["high"],
                 "l": r["low"], "c": r["close"]} for r in raw]
        return format_candles(norm)

    @app.get("/tape")
    def tape(limit: int = 50):
        decisions = engine.store.get_decisions(engine.session_id) if engine.session_id else []
        fills = account_provider().get("_fills", [])
        return merge_tape(decisions, fills, limit)

    @app.get("/coins")
    def coins():
        sz = getattr(engine.client, "sz_decimals", {})
        return [{"name": c, "szDecimals": sz[c]} for c in LIQUID_MAJORS if c in sz]

    def _summary_for(session_row: dict) -> dict:
        sid = session_row["id"]
        return session_summary(
            session_row,
            engine.store.get_fills(sid),
            engine.store.get_funding(sid),
            engine.store.get_pnl_snapshots(sid),
        )

    @app.get("/sessions")
    def sessions(mode: str | None = None):
        return [_summary_for(s) for s in engine.store.list_sessions(mode)]

    @app.get("/sessions/{session_id}")
    def session_detail(session_id: int):
        s = engine.store.get_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="sesion no encontrada")
        return {
            "summary": _summary_for(s),
            "trades": engine.store.get_fills(session_id),
            "equity_curve": engine.store.get_pnl_snapshots(session_id),
            "decisions": engine.store.get_decisions(session_id),
        }

    @app.get("/stats/global")
    def stats_global():
        summaries = [_summary_for(s) for s in engine.store.list_sessions()]
        return global_stats(summaries)

    return app
