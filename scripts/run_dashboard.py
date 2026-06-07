"""Run the dashboard reader as a separate process.

    python -m scripts.run_dashboard

Reads state through the configured sink (file or redis) — it does NOT need API keys
and can run on a different machine from the engine (e.g. a free web host reading Redis).
"""
from __future__ import annotations

import logging

from common.config import load_params
from common.logging_util import setup_logging
from dashboard.app import run_dashboard
from dashboard.sink import make_sink


def main() -> None:
    setup_logging(logging.INFO)
    params = load_params()
    sink = make_sink(params)
    d = params["dashboard"]
    logging.getLogger("run_dashboard").info(
        "Dashboard (%s sink) at http://%s:%s", params["dashboard"].get("sink", "file"),
        d["host"], d["port"])
    run_dashboard(params, sink)

if __name__ == "__main__":
    main()