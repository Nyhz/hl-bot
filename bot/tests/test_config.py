import os

from hlbot.config import Config


def _no_mode_file(monkeypatch):
    """Isolate tests from any real ~/.hlbot/mode file."""
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: "/nonexistent-hlbot-mode" if p == "~/.hlbot/mode" else p)


def test_defaults_to_testnet(monkeypatch):
    _no_mode_file(monkeypatch)
    monkeypatch.delenv("HL_TESTNET", raising=False)
    cfg = Config.from_env()
    assert cfg.testnet is True
    assert cfg.base_url == "https://api.hyperliquid-testnet.xyz"

def test_mainnet_when_flag_false(monkeypatch):
    _no_mode_file(monkeypatch)
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

def test_mode_file_prod_forces_mainnet(tmp_path, monkeypatch):
    import os as _os
    home = tmp_path
    (home / ".hlbot").mkdir()
    (home / ".hlbot" / "mode").write_text("prod")
    monkeypatch.setattr(_os.path, "expanduser", lambda p: str(home / ".hlbot" / "mode")
                        if p == "~/.hlbot/mode" else p)
    monkeypatch.delenv("HL_TESTNET", raising=False)
    cfg = Config.from_env()
    assert cfg.testnet is False


def test_mode_file_dev_overrides_testnet_false(tmp_path, monkeypatch):
    import os as _os
    mode = tmp_path / "mode"
    mode.write_text("dev")
    monkeypatch.setattr(_os.path, "expanduser",
                        lambda p: str(mode) if p == "~/.hlbot/mode" else p)
    monkeypatch.setenv("HL_TESTNET", "false")   # el mode file (dev) debe ganar
    cfg = Config.from_env()
    assert cfg.testnet is True
