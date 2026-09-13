"""KPI and container cards. Values arrive formatted; cards never compute."""
from __future__ import annotations
import streamlit as st
from app_v2.ui.formatting import esc
from app_v2.ui.help import tip


def kpi_html(label: str, value: str, sub: str = '', tone: str = 'neutral', source: str = '', unit: str = '') -> str:
    src = f'<div class="cs-src">{esc(source)}</div>' if source else ''
    u = f'<span class="unit">{esc(unit)}</span>' if unit else ''
    return (f'<div class="cs-card kpi {esc(tone)}" role="group" aria-label="{esc(label)}"><div class="cs-kpi-label">{tip(label)}</div>'
            f'<div class="cs-kpi-value">{esc(value)}{u}</div><div class="cs-kpi-sub">{esc(sub)}</div>{src}</div>')


def kpi_card(label: str, value: str, sub: str = '', tone: str = 'neutral', source: str = '', unit: str = '') -> None:
    st.html(kpi_html(label, value, sub, tone, source, unit))


def kpi_strip(kpis) -> None:
    cols = st.columns(len(kpis))
    for col, k in zip(cols, kpis):
        with col:
            kpi_card(k.label, k.value, k.sub, k.tone, k.source, getattr(k, 'unit', ''))


def card_html(title: str, body_html: str, raised: bool = False, extra_class: str = '') -> str:
    t = f'<div class="cs-card-title">{esc(title)}</div>' if title else ''
    return f'<div class="cs-card {"raised" if raised else ""} {extra_class}">{t}{body_html}</div>'


def card(title: str, body_html: str, raised: bool = False, extra_class: str = '') -> None:
    st.html(card_html(title, body_html, raised, extra_class))


def kv_html(pairs, stack: bool = False) -> str:
    """Key/value grid; `stack=True` puts the value under the key for narrow rails."""
    return f'<div class="cs-kv {"stack" if stack else ""}">' + ''.join(f'<div class="k">{tip(k)}</div><div class="v">{esc(v)}</div>' for k, v in pairs) + '</div>'


def table_html(headers, rows, numeric_cols=()) -> str:
    h = ''.join(f'<th>{esc(x)}</th>' for x in headers)
    body = ''
    for r in rows:
        body += '<tr>' + ''.join(f'<td class="{"num" if i in numeric_cols else ""}">{esc(x)}</td>' for i, x in enumerate(r)) + '</tr>'
    return f'<div style="overflow-x:auto"><table class="cs-table"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def section(title: str, caption: str = '') -> None:
    st.markdown(f'### {title}')
    if caption:
        st.markdown(f'<div class="cs-muted">{esc(caption)}</div>', unsafe_allow_html=True)
