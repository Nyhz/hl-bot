from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

MAINNET_URL = "https://api.hyperliquid.xyz"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


@dataclass
class Config:
    testnet: bool = True
    account_address: str | None = None
    secret_key: str | None = None
    control_token: str = "change-me"
    db_path: str = "data.db"
    watch_addresses: list[str] | None = None   # shadow whale: direcciones a seguir

    @classmethod
    def from_env(cls) -> "Config":
        import os.path
        mode_file = os.path.expanduser("~/.hlbot/mode")
        testnet = os.getenv("HL_TESTNET", "true").lower() != "false"
        if os.path.exists(mode_file):
            with open(mode_file) as f:
                testnet = f.read().strip() != "prod"   # prod=mainnet, cualquier otro=testnet
        watch = [a.strip() for a in os.getenv("HL_WATCH_ADDRESSES", "").split(",")
                 if a.strip()]
        return cls(
            testnet=testnet,
            account_address=os.getenv("HL_ACCOUNT_ADDRESS") or None,
            secret_key=os.getenv("HL_SECRET_KEY") or None,
            control_token=os.getenv("CONTROL_TOKEN", "change-me"),
            db_path=os.getenv("DB_PATH", "data.db"),
            watch_addresses=watch or None,
        )

    @property
    def base_url(self) -> str:
        return TESTNET_URL if self.testnet else MAINNET_URL
