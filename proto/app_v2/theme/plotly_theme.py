"""Plotly template built from the frozen tokens: dark ground, tabular fonts, compound colours, one axis style."""
from __future__ import annotations
import plotly.graph_objects as go
import plotly.io as pio
from app_v2.theme.tokens import COLORS, COMPOUNDS, FONT_STACK

TEMPLATE_NAME = 'orb_v1'


def build_template() -> go.layout.Template:
    t = go.layout.Template()
    t.layout = go.Layout(
        paper_bgcolor=COLORS['background'], plot_bgcolor=COLORS['surface'],
        font=dict(family=FONT_STACK, color=COLORS['text'], size=12),
        title=dict(font=dict(size=13, color=COLORS['text_secondary']), x=0.0, xanchor='left'),
        margin=dict(l=48, r=16, t=36, b=40),
        colorway=[COLORS['live'], COLORS['decision'], COLORS['critical'], COMPOUNDS['HARD'], COMPOUNDS['MEDIUM'], COMPOUNDS['SOFT']],
        xaxis=dict(gridcolor=COLORS['border'], zerolinecolor=COLORS['border'], linecolor=COLORS['border'], tickfont=dict(size=11, color=COLORS['text_secondary']), title=dict(font=dict(size=11, color=COLORS['text_secondary'])), showspikes=False),
        yaxis=dict(gridcolor=COLORS['border'], zerolinecolor=COLORS['border'], linecolor=COLORS['border'], tickfont=dict(size=11, color=COLORS['text_secondary']), title=dict(font=dict(size=11, color=COLORS['text_secondary']))),
        legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(size=10, color=COLORS['text_secondary']), orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
        hoverlabel=dict(bgcolor=COLORS['raised'], bordercolor=COLORS['border'], font=dict(family=FONT_STACK, size=11, color=COLORS['text'])),
        hovermode='x unified',
    )
    return t


def register() -> str:
    if TEMPLATE_NAME not in pio.templates:
        pio.templates[TEMPLATE_NAME] = build_template()
    return TEMPLATE_NAME


def apply(fig: go.Figure, height: int = 380, **layout) -> go.Figure:
    """Apply the Orb template plus per-figure overrides. Never sets colours outside the tokens."""
    fig.update_layout(template=register(), height=height, **layout)
    return fig


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip('#'); r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'
