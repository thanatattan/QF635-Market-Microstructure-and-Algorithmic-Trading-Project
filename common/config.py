"""Configuration loading: YAML params + .env secrets.

Single source of truth for parameters (config/params.yaml) and credentials (.env).
Everything else imports `load_config()` so there are no magic numbers in the code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root = parent of this file's directory (common/ -> root)
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARAMS = ROOT / "config" / "params.yaml"


@dataclass
class Credentials:
    api_key: str | None
    api_secret: str | None
    use_testnet: bool

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def load_params(path: str | Path = DEFAULT_PARAMS) -> dict[str, Any]:
    #Load the YAML parameter file into a plain dict
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_credentials() -> Credentials:
    #Load Binance testnet credentials from the .env file (if present)
    load_dotenv(ROOT / ".env")
    use_testnet = os.getenv("USE_TESTNET", "true").strip().lower() == "true"
    return Credentials(
        api_key=os.getenv("BINANCE_TESTNET_API_KEY"),
        api_secret=os.getenv("BINANCE_TESTNET_API_SECRET"),
        use_testnet=use_testnet,
    )


def load_config(path: str | Path = DEFAULT_PARAMS) -> dict[str, Any]:
    #Convenience: params dict with credentials attached under `_credentials`.
    params = load_params(path)
    params["_credentials"] = load_credentials()
    return params