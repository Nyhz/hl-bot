import os
import pytest
from hlbot.config import Config
from hlbot.hl_client import HLClient

pytestmark = pytest.mark.skipif(
    not os.getenv("HL_ACCOUNT_ADDRESS"),
    reason="requiere credenciales testnet en el entorno",
)


def test_mid_and_meta_load_from_testnet():
    cfg = Config.from_env()
    assert cfg.testnet is True  # nunca correr integracion contra mainnet por accidente
    client = HLClient(cfg)
    assert "ETH" in client.sz_decimals
    assert client.mid("ETH") > 0


def test_http_timeout_is_set():
    from hlbot.hl_client import HTTP_TIMEOUT
    client = HLClient(Config.from_env())
    assert client.info.timeout == HTTP_TIMEOUT          # toda llamada de red está acotada
    if client.exchange is not None:
        assert client.exchange.timeout == HTTP_TIMEOUT


def test_user_state_returns_account():
    client = HLClient(Config.from_env())
    state = client.user_state()
    assert "marginSummary" in state


def test_open_orders_returns_list():
    client = HLClient(Config.from_env())
    assert isinstance(client.open_orders("ETH"), list)


def test_user_fills_and_funding_return_lists():
    client = HLClient(Config.from_env())
    assert isinstance(client.user_fills(), list)
    assert isinstance(client.user_funding(0), list)


def test_schedule_cancel_volume_gated_or_ok():
    # HL gatea el dead man's switch nativo a $1M de volumen acumulado (verificado
    # 2026-07-13 en testnet; por eso existe hlbot.watchdog). Si algún día se
    # desbloquea, armar a +60s y desarmar deben funcionar.
    import time
    client = HLClient(Config.from_env())
    if client.exchange is None:
        pytest.skip("requiere clave de agente para acciones de exchange")
    resp = client.schedule_cancel(int(time.time() * 1000) + 60_000)
    if resp.get("status") == "ok":
        assert client.schedule_cancel(None).get("status") == "ok"
    else:
        assert "volume" in str(resp.get("response", "")).lower()
