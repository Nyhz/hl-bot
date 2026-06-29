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


def test_user_state_returns_account():
    client = HLClient(Config.from_env())
    state = client.user_state()
    assert "marginSummary" in state


def test_open_orders_returns_list():
    client = HLClient(Config.from_env())
    assert isinstance(client.open_orders("ETH"), list)
