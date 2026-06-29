from hlbot.config import Config

def test_defaults_to_testnet(monkeypatch):
    monkeypatch.delenv("HL_TESTNET", raising=False)
    cfg = Config.from_env()
    assert cfg.testnet is True
    assert cfg.base_url == "https://api.hyperliquid-testnet.xyz"

def test_mainnet_when_flag_false(monkeypatch):
    monkeypatch.setenv("HL_TESTNET", "false")
    cfg = Config.from_env()
    assert cfg.testnet is False
    assert cfg.base_url == "https://api.hyperliquid.xyz"

def test_reads_credentials(monkeypatch):
    monkeypatch.setenv("HL_ACCOUNT_ADDRESS", "0xabc")
    monkeypatch.setenv("CONTROL_TOKEN", "tok")
    cfg = Config.from_env()
    assert cfg.account_address == "0xabc"
    assert cfg.control_token == "tok"
