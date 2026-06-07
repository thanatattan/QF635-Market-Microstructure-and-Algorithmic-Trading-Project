"""Consistent logging setup used by scripts and the engine."""
from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] %(name)s: %(message)s",
        level=level,
    )
    # python-binance / websockets can be noisy at DEBUG
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)