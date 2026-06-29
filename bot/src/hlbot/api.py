from __future__ import annotations
import asyncio
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from hlbot.models import SessionConfig, RiskLimits
from hlbot.session_engine import SessionEngine


class LimitsBody(BaseModel):
    max_position_notional: float
    max_open_positions: int
    max_leverage: float
    daily_loss_limit: float
    total_loss_limit: float


class LaunchBody(BaseModel):
    watchlist: list[str]
    capital: float
    limits: LimitsBody
    grid_n: int = 10
    grid_range_pct: float = 0.03
    adx_threshold: float = 25.0


class KillBody(BaseModel):
    confirm: bool


def create_app(engine: SessionEngine, control_token: str,
               market_state_provider) -> FastAPI:
    app = FastAPI(title="hlbot")

    def _auth(token: str | None):
        if token != control_token:
            raise HTTPException(status_code=401, detail="token de control invalido")

    @app.get("/state")
    def state():
        return engine.snapshot(market_state_provider())

    @app.get("/history")
    def history():
        if engine.session_id is None:
            return {"decisions": []}
        return {"decisions": engine.store.get_decisions(engine.session_id)}

    @app.post("/session/launch")
    def launch(body: LaunchBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        limits = RiskLimits(**body.limits.model_dump())
        cfg = SessionConfig(watchlist=body.watchlist, capital=body.capital,
                            limits=limits, grid_n=body.grid_n,
                            grid_range_pct=body.grid_range_pct,
                            adx_threshold=body.adx_threshold)
        try:
            engine.launch(cfg)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
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
                await websocket.send_json(engine.snapshot(market_state_provider()))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    return app
