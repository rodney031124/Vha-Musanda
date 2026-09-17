# app.py — Professional Ash Dam Monitoring Dashboard
# Industrial SCADA-style visualization for coal mine ash impoundments
import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objects as go
import numpy as np
import requests

app = dash.Dash(__name__, title="Ash Dam Monitor")

# ═══════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════
DAM_DIAMETER_M    = 60.0     # nominal dam footprint (for display)
DAM_WALL_HEIGHT_M = 8.0      # height of embankment (visual only)
CREST_RADIUS      = 12.0     # radius at dam crest (Plotly units)
TOE_RADIUS        = 20.0     # radius at dam toe
POND_RADIUS       = 9.0      # default pond radius
MAX_WATER_DEPTH   = 6.0      # max water depth inside dam (m, display)

ALERT_DISTANCE_CM = 20.0     # must match ESP32 ALERT_DISTANCE_CM
SENSOR_MAX_CM     = 400.0    # HC-SR04 nominal range

BRIDGE_URL        = "http://127.0.0.1:5000/data"

# ═══════════════════════════════════════════════════════════════════
#  DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════════
C = {
    "bg":         "#0b0f17",
    "panel":      "#111826",
    "panel_alt":  "#0e141f",
    "border":     "#1e2938",
    "grid":       "#1c2533",
    "text":       "#e6edf5",
    "text_dim":   "#8291a6",
    "text_mute":  "#5a6a80",
    "accent":     "#22d3ee",     # cyan
    "safe":       "#10b981",     # emerald
    "warn":       "#f59e0b",     # amber
    "alert":      "#ef4444",     # red
    "info":       "#3b82f6",     # blue
}

def card(children, **kwargs):
    style = {
        "backgroundColor": C["panel"],
        "border":          f"1px solid {C['border']}",
        "borderRadius":    "8px",
        "padding":         "18px 20px",
    }
    style.update(kwargs.pop("style", {}))
    return html.Div(children, style=style, **kwargs)


def section_label(text):
    return html.Div(text, style={
        "fontSize": "11px",
        "fontWeight": "600",
        "letterSpacing": "1.6px",
        "textTransform": "uppercase",
        "color": C["text_mute"],
        "marginBottom": "10px",
    })


# ═══════════════════════════════════════════════════════════════════
#  3D ASH DAM MODEL
#  A truncated-cone impoundment: sloped embankment from toe to crest,
#  flat ash surface inside, and a rising pond when alert is active.
# ═══════════════════════════════════════════════════════════════════
def make_ash_dam_3d(water_level_pct, status):
    """
    water_level_pct: 0..100 (0 = empty pond, 100 = full to crest)
    status: 'NORMAL' | 'WARNING' | 'ALERT'
    """
    fig = go.Figure()

    # ── 1. Terrain base (flat ground) ──────────────────────────────
    g_lim = TOE_RADIUS + 8
    xg, yg = np.meshgrid(np.linspace(-g_lim, g_lim, 40),
                         np.linspace(-g_lim, g_lim, 40))
    zg = np.zeros_like(xg)

    fig.add_trace(go.Surface(
        x=xg, y=yg, z=zg,
        colorscale=[[0, "#1a2130"], [1, "#1a2130"]],
        showscale=False, opacity=0.9,
        name="Ground", hoverinfo="skip",
    ))

    # ── 2. Embankment (sloped ring from toe to crest) ──────────────
    theta = np.linspace(0, 2 * np.pi, 80)
    r_ring = np.linspace(TOE_RADIUS, CREST_RADIUS, 20)
    theta_g, r_g = np.meshgrid(theta, r_ring)
    x_wall = r_g * np.cos(theta_g)
    y_wall = r_g * np.sin(theta_g)
    # Height ramps from 0 at toe to DAM_WALL_HEIGHT at crest
    z_wall = DAM_WALL_HEIGHT_M * (TOE_RADIUS - r_g) / (TOE_RADIUS - CREST_RADIUS)

    fig.add_trace(go.Surface(
        x=x_wall, y=y_wall, z=z_wall,
        colorscale=[
            [0.0, "#3b4252"], [0.4, "#4a5468"],
            [0.7, "#5d687f"], [1.0, "#6e7a92"],
        ],
        showscale=False, opacity=1.0,
        name="Ash Embankment",
        hovertemplate="Embankment<br>Elev: %{z:.1f} m<extra></extra>",
    ))

    # ── 3. Crest rim (visual outline) ──────────────────────────────
    x_crest = CREST_RADIUS * np.cos(theta)
    y_crest = CREST_RADIUS * np.sin(theta)
    z_crest = np.full_like(x_crest, DAM_WALL_HEIGHT_M)
    fig.add_trace(go.Scatter3d(
        x=x_crest, y=y_crest, z=z_crest,
        mode="lines",
        line=dict(color="#94a3b8", width=4),
        name="Dam Crest", hoverinfo="skip",
    ))

    # ── 4. Ash surface inside the dam (flat, slightly darker) ──────
    r_ash = np.linspace(0, CREST_RADIUS, 25)
    theta_ash = np.linspace(0, 2 * np.pi, 80)
    r_a, th_a = np.meshgrid(r_ash, theta_ash)
    x_ash = r_a * np.cos(th_a)
    y_ash = r_a * np.sin(th_a)
    z_ash = np.full_like(x_ash, DAM_WALL_HEIGHT_M - 0.15)  # slightly below crest

    fig.add_trace(go.Surface(
        x=x_ash, y=y_ash, z=z_ash,
        colorscale=[[0, "#2a2f3d"], [1, "#2a2f3d"]],
        showscale=False, opacity=1.0,
        name="Ash Surface", hoverinfo="skip",
    ))

    # ── 5. Water pond (rising with water_level_pct) ────────────────
    water_depth = MAX_WATER_DEPTH * (water_level_pct / 100.0)

    if water_depth > 0.05:
        # Pond radius scales a bit with depth (like a real pond)
        pond_r = POND_RADIUS * (0.55 + 0.45 * (water_level_pct / 100.0))
        r_p = np.linspace(0, pond_r, 25)
        th_p = np.linspace(0, 2 * np.pi, 80)
        r_pg, th_pg = np.meshgrid(r_p, th_p)
        x_pond = r_pg * np.cos(th_pg)
        y_pond = r_pg * np.sin(th_pg)

        z_top  = np.full_like(x_pond, DAM_WALL_HEIGHT_M - 0.15 + water_depth)
        z_base = np.full_like(x_pond, DAM_WALL_HEIGHT_M - 0.15)

        if status == "ALERT":
            water_col = "#dc2626"
            edge_col  = "#f87171"
        elif status == "WARNING":
            water_col = "#d97706"
            edge_col  = "#fbbf24"
        else:
            water_col = "#0ea5e9"
            edge_col  = "#22d3ee"

        # Water top surface
        fig.add_trace(go.Surface(
            x=x_pond, y=y_pond, z=z_top,
            colorscale=[[0, water_col], [1, water_col]],
            showscale=False, opacity=0.92,
            name="Pond Surface",
            hovertemplate="Pond<br>Elev: %{z:.2f} m<extra></extra>",
        ))

        # Pond outline ring for definition
        th_ring = np.linspace(0, 2 * np.pi, 80)
        x_ring = pond_r * np.cos(th_ring)
        y_ring = pond_r * np.sin(th_ring)
        z_ring = np.full_like(x_ring, DAM_WALL_HEIGHT_M - 0.15 + water_depth)

        fig.add_trace(go.Scatter3d(
            x=x_ring, y=y_ring, z=z_ring,
            mode="lines",
            line=dict(color=edge_col, width=5),
            name="Pond Edge", hoverinfo="skip",
        ))

    # ── 6. Safe-level reference ring (dashed) ──────────────────────
    z_safe = DAM_WALL_HEIGHT_M - 0.15 + MAX_WATER_DEPTH * 0.70
    x_s = (POND_RADIUS + 1.5) * np.cos(theta)
    y_s = (POND_RADIUS + 1.5) * np.sin(theta)
    z_s = np.full_like(x_s, z_safe)

    fig.add_trace(go.Scatter3d(
        x=x_s, y=y_s, z=z_s,
        mode="lines",
        line=dict(color="#eab308", width=4, dash="dash"),
        name="Safe Level", hoverinfo="skip",
    ))

    # ── Layout ─────────────────────────────────────────────────────
    fig.update_layout(
        scene=dict(
            xaxis=dict(visible=False, range=[-g_lim, g_lim]),
            yaxis=dict(visible=False, range=[-g_lim, g_lim]),
            zaxis=dict(
                title=dict(text="Elevation (m)", font=dict(color=C["text_dim"], size=11)),
                range=[-1, DAM_WALL_HEIGHT_M + MAX_WATER_DEPTH + 2],
                gridcolor=C["grid"], color=C["text_dim"],
                tickfont=dict(size=10),
            ),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=0.55),
            bgcolor="rgba(0,0,0,0)",
            camera=dict(
                eye=dict(x=1.5, y=-1.5, z=1.15),
                center=dict(x=0, y=0, z=0.1),
            ),
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        height=560,
    )
    return fig


# ═══════════════════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════════════════
app.layout = html.Div(
    style={
        "backgroundColor": C["bg"],
        "color":           C["text"],
        "fontFamily":      "'Inter', 'Segoe UI', system-ui, sans-serif",
        "minHeight":       "100vh",
        "padding":         "20px 26px",
        "fontFeatureSettings": "'tnum' 1",
    },
    children=[
        # ═══ HEADER BAR ═══
        html.Div(
            style={
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
                "paddingBottom": "16px",
                "borderBottom": f"1px solid {C['border']}",
                "marginBottom": "20px",
            },
            children=[
                html.Div([
                    html.Div("ASH DAM MONITORING SYSTEM", style={
                        "fontSize": "20px", "fontWeight": "700",
                        "letterSpacing": "1.2px", "color": C["text"],
                    }),
                    html.Div("Real-time Volumetric Surveillance · Coal Mine Tailings Facility", style={
                        "fontSize": "12px", "color": C["text_dim"],
                        "marginTop": "2px", "letterSpacing": "0.4px",
                    }),
                ]),
                html.Div(id="header-status", style={
                    "display": "flex", "alignItems": "center",
                    "gap": "20px",
                }),
            ],
        ),

        # ═══ KPI STRIP ═══
        html.Div(id="kpi-strip", style={
            "display": "grid",
            "gridTemplateColumns": "repeat(4, 1fr)",
            "gap": "14px",
            "marginBottom": "18px",
        }),

        # ═══ MAIN GRID: 3D + SIDE PANEL ═══
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "1.9fr 1fr",
                "gap": "16px",
                "marginBottom": "18px",
            },
            children=[
                # ── LEFT: 3D DAM ──
                card([
                    html.Div(
                        style={
                            "display": "flex",
                            "justifyContent": "space-between",
                            "alignItems": "center",
                            "marginBottom": "8px",
                        },
                        children=[
                            section_label("3D Ash Dam Model · Volumetric View"),
                            html.Div(id="dam-caption", style={
                                "fontSize": "11px", "color": C["text_dim"],
                                "letterSpacing": "0.5px",
                            }),
                        ],
                    ),
                    dcc.Graph(
                        id="dam-3d",
                        config={"displayModeBar": False, "responsive": True},
                        style={"height": "560px"},
                    ),
                ], style={"padding": "16px 18px 8px 18px"}),

                # ── RIGHT: STATUS + CONTROLS ──
                html.Div(
                    style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                    children=[
                        card([
                            section_label("Subsystem Status"),
                            html.Div(id="system-status"),
                        ]),
                        card([
                            section_label("System Controls"),
                            html.Button(
                                "⚠  FORCE DISPLAY ALERT",
                                id="anomaly-btn", n_clicks=0,
                                style={
                                    "width": "100%", "padding": "12px",
                                    "backgroundColor": "rgba(239,68,68,0.12)",
                                    "color": C["alert"],
                                    "border": f"1px solid rgba(239,68,68,0.4)",
                                    "borderRadius": "6px",
                                    "fontSize": "12px", "fontWeight": "600",
                                    "letterSpacing": "1px",
                                    "cursor": "pointer",
                                    "marginBottom": "10px",
                                },
                            ),
                            html.Button(
                                "↺  RESET SESSION",
                                id="reset-btn", n_clicks=0,
                                style={
                                    "width": "100%", "padding": "10px",
                                    "backgroundColor": "transparent",
                                    "color": C["text_dim"],
                                    "border": f"1px solid {C['border']}",
                                    "borderRadius": "6px",
                                    "fontSize": "12px", "fontWeight": "500",
                                    "letterSpacing": "1px",
                                    "cursor": "pointer",
                                },
                            ),
                        ]),
                        card([
                            section_label("Alert Events"),
                            html.Div(id="alert-count", style={
                                "fontSize": "48px", "fontWeight": "700",
                                "color": C["alert"], "lineHeight": "1",
                                "fontVariantNumeric": "tabular-nums",
                            }),
                        ]),
                    ],
                ),
            ],
        ),

        # ═══ TREND CHART ═══
        card([
            html.Div(
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center",
                    "marginBottom": "10px",
                },
                children=[
                    section_label("Distance Trend · Last 60 Samples"),
                    html.Div("— Alert Threshold · 20 cm", style={
                        "fontSize": "11px", "color": C["warn"],
                        "letterSpacing": "0.5px",
                    }),
                ],
            ),
            dcc.Graph(id="trend", config={"displayModeBar": False},
                      style={"height": "240px"}),
        ], style={"padding": "16px 18px 8px 18px"}),

        # ═══ INTERNALS ═══
        dcc.Interval(id="tick", interval=1000, n_intervals=0),
        dcc.Store(id="alert-counter", data=0),
        dcc.Store(id="force-alert",    data=False),
        dcc.Store(id="prev-alert",     data=False),
    ],
)


# ═══════════════════════════════════════════════════════════════════
#  KPI / STATUS BUILDERS
# ═══════════════════════════════════════════════════════════════════
def kpi(label, value, unit="", color=None, sub=""):
    return html.Div(
        style={
            "backgroundColor": C["panel"],
            "border": f"1px solid {C['border']}",
            "borderRadius": "8px",
            "padding": "14px 16px",
        },
        children=[
            html.Div(label, style={
                "fontSize": "10px", "fontWeight": "600",
                "letterSpacing": "1.4px", "textTransform": "uppercase",
                "color": C["text_mute"], "marginBottom": "8px",
            }),
            html.Div([
                html.Span(value, style={
                    "fontSize": "28px", "fontWeight": "700",
                    "color": color or C["text"],
                    "fontVariantNumeric": "tabular-nums",
                    "lineHeight": "1",
                }),
                html.Span(f" {unit}", style={
                    "fontSize": "13px", "color": C["text_dim"],
                    "marginLeft": "4px",
                }) if unit else None,
            ]),
            html.Div(sub, style={
                "fontSize": "11px", "color": C["text_mute"],
                "marginTop": "6px", "letterSpacing": "0.3px",
            }) if sub else None,
        ],
    )


def indicator(label, active, active_color):
    return html.Div(
        style={
            "display": "flex", "alignItems": "center",
            "padding": "8px 0",
            "borderBottom": f"1px solid {C['border']}",
        },
        children=[
            html.Div(style={
                "width": "8px", "height": "8px", "borderRadius": "50%",
                "backgroundColor": active_color if active else "#2a3441",
                "boxShadow": f"0 0 8px {active_color}" if active else "none",
                "marginRight": "12px", "flexShrink": "0",
            }),
            html.Div(label, style={
                "fontSize": "12px", "letterSpacing": "0.6px",
                "color": C["text"] if active else C["text_mute"],
                "textTransform": "uppercase", "fontWeight": "500",
                "flex": "1",
            }),
            html.Div("ON" if active else "OFF", style={
                "fontSize": "11px", "fontWeight": "600",
                "letterSpacing": "0.8px",
                "color": active_color if active else C["text_mute"],
            }),
        ],
    )


# ═══════════════════════════════════════════════════════════════════
#  CALLBACK
# ═══════════════════════════════════════════════════════════════════
@app.callback(
    [Output("dam-3d", "figure"),
     Output("kpi-strip", "children"),
     Output("header-status", "children"),
     Output("system-status", "children"),
     Output("trend", "figure"),
     Output("alert-count", "children"),
     Output("dam-caption", "children"),
     Output("alert-counter", "data"),
     Output("force-alert", "data"),
     Output("prev-alert", "data")],
    [Input("tick", "n_intervals"),
     Input("anomaly-btn", "n_clicks"),
     Input("reset-btn", "n_clicks")],
    [State("alert-counter", "data"),
     State("force-alert", "data"),
     State("prev-alert", "data")]
)
def update(n, anomaly_clicks, reset_clicks, alert_count, force_alert, prev_alert):
    ctx = dash.callback_context
    triggered = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else "tick"

    if triggered == "anomaly-btn" and anomaly_clicks:
        force_alert = True
    if triggered == "reset-btn" and reset_clicks:
        alert_count = 0
        force_alert = False
        prev_alert  = False

    # ── fetch ──
    try:
        r = requests.get(BRIDGE_URL, timeout=2)
        p = r.json()
        connected  = p.get("connected", False)
        distance   = p.get("distance")
        alert      = bool(p.get("alert", False))
        buzzer     = bool(p.get("buzzer", False))
        led_green  = bool(p.get("led_green", False))
        led_red    = bool(p.get("led_red", False))
        history    = p.get("history", [])
    except Exception:
        connected, distance, alert = False, None, False
        buzzer = led_green = led_red = False
        history = []

    # ── disconnected state ──
    if not connected or distance is None:
        kpis = [
            kpi("Connection", "OFFLINE", color=C["alert"], sub="Bridge unreachable"),
            kpi("Distance", "—", "cm", color=C["text_mute"]),
            kpi("Status", "WAITING", color=C["warn"]),
            kpi("Alerts", str(alert_count), color=C["alert"]),
        ]
        header = html.Div("⌛ AWAITING SENSOR LINK", style={
            "fontSize": "12px", "fontWeight": "600",
            "letterSpacing": "1.5px", "color": C["warn"],
            "padding": "8px 16px", "borderRadius": "6px",
            "backgroundColor": "rgba(245,158,11,0.1)",
            "border": "1px solid rgba(245,158,11,0.3)",
        })
        dam_fig = make_ash_dam_3d(0, "NORMAL")
        trend_fig = go.Figure()
        trend_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=C["text_dim"]),
        )
        return (dam_fig, kpis, header, html.Div("—"), trend_fig,
                str(alert_count), "No data", alert_count, force_alert, prev_alert)

    # ── force ──
    if force_alert:
        alert = True

    # ── derive values ──
    # Map distance to a "water level %" of the pond
    #   far (400 cm) = 0%     near (0 cm) = 100%
    dist_clamped = max(0.0, min(distance, SENSOR_MAX_CM))
    water_level_pct = 100.0 * (1.0 - dist_clamped / SENSOR_MAX_CM)

    # Threshold: alert at 20 cm → approx 95%
    threshold_pct = 100.0 * (1.0 - ALERT_DISTANCE_CM / SENSOR_MAX_CM)

    # Status classification (3-tier for nicer visuals)
    if alert:
        status = "ALERT"
        status_color = C["alert"]
        status_label = "ALERT · Object Detected"
    elif water_level_pct > 70:
        status = "WARNING"
        status_color = C["warn"]
        status_label = "WARNING · Approaching"
    else:
        status = "NORMAL"
        status_color = C["safe"]
        status_label = "NOMINAL"

    # ── alert counter ──
    if alert and not prev_alert:
        alert_count += 1
    prev_alert = alert

    # ── KPIs ──
    kpis = [
        kpi("Sensor Distance", f"{distance:.1f}", "cm",
            color=C["accent"],
            sub=f"Threshold: {ALERT_DISTANCE_CM:.0f} cm"),
        kpi("Pond Level (derived)", f"{water_level_pct:.1f}", "%",
            color=status_color,
            sub=f"{MAX_WATER_DEPTH * water_level_pct/100:.2f} m depth est."),
        kpi("Status", status,
            color=status_color,
            sub=status_label),
        kpi("Alerts This Session", str(alert_count),
            color=C["alert"] if alert_count else C["text"],
            sub="Edge-triggered events"),
    ]

    # ── header status ──
    header = html.Div([
        html.Div([
            html.Span("●", style={
                "color": C["safe"], "marginRight": "8px",
                "fontSize": "14px",
            }),
            html.Span("SENSOR LINK", style={
                "fontSize": "10px", "letterSpacing": "1.2px",
                "color": C["text_dim"], "marginRight": "6px",
            }),
            html.Span("ACTIVE", style={
                "fontSize": "11px", "fontWeight": "600",
                "color": C["safe"],
            }),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div([
            html.Span("●", style={
                "color": status_color, "marginRight": "8px",
                "fontSize": "14px",
            }),
            html.Span(status, style={
                "fontSize": "11px", "fontWeight": "700",
                "letterSpacing": "1.4px", "color": status_color,
            }),
        ], style={"display": "flex", "alignItems": "center"}),
    ])

    # ── status list ──
    status_children = html.Div([
        indicator("Sensor Link", connected, C["safe"]),
        indicator("Green LED · Safe", led_green, C["safe"]),
        indicator("Red LED · Alert", led_red, C["alert"]),
        indicator("Buzzer", buzzer, C["warn"]),
    ])

    # ── trend chart ──
    times  = [h["time"][11:19] for h in history]  # HH:MM:SS
    values = [h["distance"]    for h in history]

    trend_fig = go.Figure()
    trend_fig.add_trace(go.Scatter(
        x=times, y=values, mode="lines",
        line=dict(color=C["accent"], width=2, shape="spline"),
        fill="tozeroy",
        fillcolor="rgba(34,211,238,0.08)",
        name="Distance",
        hovertemplate="%{y:.2f} cm<extra></extra>",
    ))
    trend_fig.add_hline(
        y=ALERT_DISTANCE_CM,
        line=dict(color=C["warn"], width=1.5, dash="dash"),
    )
    trend_fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C["text_dim"], size=11),
        xaxis=dict(
            gridcolor=C["grid"], showgrid=False,
            linecolor=C["border"], tickfont=dict(size=10),
        ),
        yaxis=dict(
            gridcolor=C["grid"], range=[0, SENSOR_MAX_CM],
            title=dict(text="Distance (cm)",
                       font=dict(color=C["text_dim"], size=11)),
            tickfont=dict(size=10),
        ),
        margin=dict(l=50, r=16, t=8, b=32),
        showlegend=False,
        hovermode="x unified",
    )

    # ── 3D figure ──
    dam_fig = make_ash_dam_3d(water_level_pct, status)

    caption = f"Pond level {water_level_pct:.0f}% · Safe threshold {threshold_pct:.0f}%"

    return (dam_fig, kpis, header, status_children, trend_fig,
            str(alert_count), caption, alert_count, force_alert, prev_alert)


if __name__ == "__main__":
    app.run(debug=False, port=8050)