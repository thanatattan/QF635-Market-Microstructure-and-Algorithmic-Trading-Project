"""Dashboard reader (Dash/Plotly).

Reads state through a StateSink (file or redis), so it runs as a SEPARATE process
from the engine. Shows a staleness indicator and (unless read_only) a kill-switch
that writes back through the sink.
"""
from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

from dashboard.sink import StateSink, make_sink

CARD = {"padding": "10px 16px", "background": "#1e1e2e", "borderRadius": "8px",
        "color": "#cdd6f4", "minWidth": "130px", "textAlign": "center"}
LABEL = {"fontSize": "11px", "color": "#9399b2", "textTransform": "uppercase"}
VALUE = {"fontSize": "20px", "fontWeight": "bold"}


def _dt(ts_ms) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def _age_seconds(payload: dict) -> float | None:
    pub = payload.get("published_at")
    if not pub:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds()
    except ValueError:
        return None


def create_app(sink: StateSink, params: dict) -> Dash:
    app = Dash(__name__)
    d = params["dashboard"]
    refresh = int(d["refresh_ms"])
    stale_after = float(d.get("stale_after_seconds", 10))
    read_only = bool(d.get("read_only", False))

    controls = [html.Div(id="stale", style={"color": "#f38ba8", "fontWeight": "bold"})]
    if not read_only:
        controls.insert(0, html.Button(
            "Toggle KILL SWITCH", id="kill-btn", n_clicks=0,
            style={"padding": "8px 16px", "background": "#f38ba8", "border": "none",
                   "borderRadius": "6px", "cursor": "pointer"}))

    app.layout = html.Div(
        style={"background": "#11111b", "fontFamily": "Segoe UI, sans-serif",
               "padding": "16px", "minHeight": "100vh"},
        children=[
            html.H2("BTCUSDT Short-Squeeze Momentum — Live Paper Trading",
                    style={"color": "#cdd6f4"}),
            html.Div(id="cards", style={"display": "flex", "gap": "10px", "flexWrap": "wrap"}),
            html.Div(controls, style={"display": "flex", "gap": "16px", "alignItems": "center",
                                      "margin": "12px 0"}),
            html.Div(id="signal-conditions", style={"color": "#cdd6f4"}),
            dcc.Graph(id="price-chart"),
            dcc.Graph(id="equity-chart"),
            html.Div(style={"display": "flex", "gap": "10px"}, children=[
                dcc.Graph(id="cvd-chart", style={"flex": 1}),
                dcc.Graph(id="oi-chart", style={"flex": 1}),
            ]),
            dcc.Interval(id="tick", interval=refresh, n_intervals=0),
        ],
    )

    if not read_only:
        @app.callback(Output("kill-btn", "children"), Input("kill-btn", "n_clicks"),
                      prevent_initial_call=True)
        def _toggle_kill(_n):
            new = not sink.get_kill()
            sink.set_kill(new)
            return "KILL SWITCH: ON" if new else "Toggle KILL SWITCH"

    @app.callback(
        Output("cards", "children"), Output("signal-conditions", "children"),
        Output("stale", "children"), Input("tick", "n_intervals"))
    def _cards(_):
        s = sink.read_latest()
        if not s:
            return [html.Div("Waiting for first bar…", style=CARD)], "", ""

        age = _age_seconds(s)
        stale = "" if age is None or age <= stale_after else f"⚠ DATA STALE ({age:.0f}s since last update)"

        pos = s.get("position", {})
        risk = s.get("risk", {})

        def card(label, value, color="#cdd6f4"):
            return html.Div(style=CARD, children=[html.Div(label, style=LABEL),
                                                  html.Div(value, style={**VALUE, "color": color})])

        state_color = {"CONFIRMED": "#a6e3a1", "TRIGGERED": "#f9e2af",
                       "BUILDUP": "#89b4fa", "IDLE": "#9399b2"}.get(s.get("signal_state"), "#cdd6f4")
        pnl = pos.get("realized_pnl", 0) + pos.get("unrealized_pnl", 0)
        cards = [
            card("Signal", s.get("signal_state", "-"), state_color),
            card("Equity", f"${pos.get('equity', 0):,.0f}"),
            card("Total PnL", f"${pnl:,.0f}", "#a6e3a1" if pnl >= 0 else "#f38ba8"),
            card("Position", f"{pos.get('position', 0):.4f}"),
            card("Unreal PnL", f"${pos.get('unrealized_pnl', 0):,.0f}"),
            card("Drawdown", f"{risk.get('current_drawdown', 0):.1%}",
                 "#f38ba8" if risk.get("current_drawdown", 0) > 0.05 else "#cdd6f4"),
            card("VaR 99%", f"${s.get('var', 0):,.0f}"),
            card("VaR 99% hist", f"${s.get('var_historical', 0):,.0f}"),
            card("Funding", f"{(s.get('funding_rate') or 0)*100:.4f}%"),
            card("Kill", "ON" if risk.get("kill_switch") else "off",
                 "#f38ba8" if risk.get("kill_switch") else "#9399b2"),
        ]

        def conds(title, dd):
            return f"{title}: " + " ".join(f"{'✅' if v else '⬜'}{k}" for k, v in dd.items())
        cond_text = html.Div([
            html.Div(conds("Build-up", s.get("buildup_conditions", {}))),
            html.Div(conds("Confirm", s.get("confirm_conditions", {}))),
            html.Div(f"Trend: {'✅ uptrend' if s.get('trend_ok', True) else '⬜ downtrend (longs blocked)'}"),
            html.Div(s.get("reason", ""), style={"color": "#9399b2", "fontSize": "12px"}),
        ])
        return cards, cond_text, stale

    @app.callback(Output("price-chart", "figure"), Input("tick", "n_intervals"))
    def _price(_):
        h = sink.read_latest().get("history", {})
        x = [_dt(t) for t in h.get("ts", [])]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=h.get("price", []), name="Close", line=dict(color="#89b4fa")))
        fig.add_trace(go.Scatter(x=x, y=h.get("breakout", []), name="1h Breakout",
                                 line=dict(color="#f9e2af", dash="dot")))
        st = h.get("state", [])
        px = h.get("price", [])
        ex = [x[i] for i, v in enumerate(st) if v == "CONFIRMED"]
        ey = [px[i] for i, v in enumerate(st) if v == "CONFIRMED"]
        fig.add_trace(go.Scatter(x=ex, y=ey, mode="markers", name="Squeeze entry",
                                 marker=dict(color="#a6e3a1", size=10, symbol="triangle-up")))
        _style(fig, "Price & Breakout")
        return fig

    @app.callback(Output("equity-chart", "figure"), Input("tick", "n_intervals"))
    def _equity(_):
        h = sink.read_latest().get("history", {})
        x = [_dt(t) for t in h.get("ts", [])]
        fig = go.Figure(go.Scatter(x=x, y=h.get("equity", []), name="Equity", line=dict(color="#a6e3a1")))
        _style(fig, "Equity Curve")
        return fig

    @app.callback(Output("cvd-chart", "figure"), Input("tick", "n_intervals"))
    def _cvd(_):
        h = sink.read_latest().get("history", {})
        x = [_dt(t) for t in h.get("ts", [])]
        fig = go.Figure(go.Scatter(x=x, y=h.get("cvd", []), name="CVD", line=dict(color="#cba6f7")))
        _style(fig, "Cumulative Volume Delta")
        return fig

    @app.callback(Output("oi-chart", "figure"), Input("tick", "n_intervals"))
    def _oi(_):
        h = sink.read_latest().get("history", {})
        x = [_dt(t) for t in h.get("ts", [])]
        fig = go.Figure(go.Scatter(x=x, y=h.get("oi", []), name="Open Interest", line=dict(color="#fab387")))
        _style(fig, "Open Interest")
        return fig

    return app


def _style(fig: go.Figure, title: str) -> None:
    fig.update_layout(
        title=title, template="plotly_dark", height=300,
        margin=dict(l=40, r=20, t=40, b=30), paper_bgcolor="#11111b",
        plot_bgcolor="#181825", legend=dict(orientation="h", y=1.1))


def run_dashboard(params: dict, sink: StateSink | None = None) -> None:
    sink = sink or make_sink(params)
    app = create_app(sink, params)
    d = params["dashboard"]
    app.run(host=d["host"], port=int(d["port"]), debug=False)