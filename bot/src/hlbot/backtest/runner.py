from __future__ import annotations
from hlbot.models import MarketState
from hlbot.session_engine import SessionEngine
from hlbot.backtest.broker import BacktestBroker
from hlbot.backtest.data import funding_at
from hlbot.backtest.metrics import compute_metrics

SNAPSHOT_EVERY = 5   # velas


class CaptureStore:
    def __init__(self):
        self.decisions: list[dict] = []
        self.current_ts = 0

    def create_session(self, watchlist, capital, mode="backtest"):
        return 1

    def end_session(self, sid):
        pass

    def record_decision(self, sid, coin, action, reason):
        self.decisions.append({"ts": self.current_ts, "coin": coin,
                               "action": action, "reason": reason})

    def record_risk_event(self, sid, kind, detail):
        pass

    def record_pnl_snapshot(self, sid, pnl):
        pass


def run_backtest(coin, candles, funding_rows, cfg, sz_decimals) -> dict:
    if not candles:
        return {"metrics": compute_metrics([], [], 0.0),
                "equity_curve": [], "trades": [], "decisions": []}
    broker = BacktestBroker(capital=cfg.capital, sz_decimals=sz_decimals)
    store = CaptureStore()
    if candles:
        broker.set_price(coin, candles[0].close)   # precio inicial para launch/set_anchor
        broker.set_ts(candles[0].t // 1000)
    engine = SessionEngine(broker, store)
    engine.launch(cfg)
    equity_curve: list[dict] = []
    for i, candle in enumerate(candles):
        fr = funding_at(funding_rows, candle.t)
        broker.step(coin, candle, fr)
        store.current_ts = candle.t // 1000
        ms = MarketState(coin=coin, mid=candle.close, candles=candles[:i + 1], funding_rate=fr)
        engine.tick({coin: ms})
        if i % SNAPSHOT_EVERY == 0:
            equity_curve.append({"ts": candle.t // 1000,
                                 "total_pnl": float(broker.user_state()["marginSummary"]["accountValue"])})
    # cierre final para realizar PnL y un último punto de equity
    broker.market_close(coin)
    if candles:
        final_pt = {"ts": candles[-1].t // 1000,
                    "total_pnl": float(broker.user_state()["marginSummary"]["accountValue"])}
        if equity_curve and equity_curve[-1]["ts"] == final_pt["ts"]:
            equity_curve[-1] = final_pt
        else:
            equity_curve.append(final_pt)
    metrics = compute_metrics(equity_curve, broker.fills, broker.funding_total)
    return {"metrics": metrics, "equity_curve": equity_curve,
            "trades": broker.fills, "decisions": store.decisions}
