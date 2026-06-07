"""WSGI entrypoint for serving the dashboard under a production server (gunicorn).

    gunicorn -b 0.0.0.0:8050 dashboard.wsgi:server

Serves the read-only-capable dashboard reader. The engine runs as its own process
(scripts.run_live) and publishes through the same sink.
"""
from common.config import load_params
from dashboard.app import create_app
from dashboard.sink import make_sink

_params = load_params()
app = create_app(make_sink(_params), _params)
server = app.server   # the Flask WSGI app gunicorn binds to