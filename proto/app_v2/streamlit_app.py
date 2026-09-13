"""Orb v1 premium dashboard shell. Run from proto/:
    ../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true
No page imports a model; every page consumes view models from app_v2/services. Offline by construction.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title='Orb v1', layout='wide', initial_sidebar_state='expanded',
                   menu_items={'Get help': None, 'Report a bug': None, 'About': 'Orb v1 · live tyre intelligence · offline build'})

from app_v2.pages import landing, pre_race, live_predictor, decision_board, driver_feedback, ghost_strategy, generalisation, validation  # noqa: E402
from app_v2.pages import common  # noqa: E402
from app_v2.ui import shell, model_guide  # noqa: E402
from app_v2.pages import guided_demo  # noqa: E402

PAGES = {
    'demo': st.Page(guided_demo.render, title='Guided demo', url_path='demo'),
    'landing': st.Page(landing.render, title='Landing', default=True),
    'prerace': st.Page(pre_race.render, title='Pre-race plan', url_path='pre-race'),
    'live': st.Page(live_predictor.render, title='Live Predictor', url_path='live'),
    'decision': st.Page(decision_board.render, title='Decision board', url_path='decision'),
    'feedback': st.Page(driver_feedback.render, title='Driver feedback', url_path='feedback'),
    'ghost': st.Page(ghost_strategy.render, title='Ghost Strategy', url_path='ghost'),
    'generalisation': st.Page(generalisation.render, title='Generalisation', url_path='generalisation'),
    'validation': st.Page(validation.render, title='Validation', url_path='validation'),
}
st.session_state['_pages'] = PAGES
nav = st.navigation(list(PAGES.values()), position='hidden')
ctx = None
if nav.url_path == 'demo':
    shell.inject_css(False)
else:
    ctx = common.bootstrap(page=nav.url_path)
    shell.inject_css(ctx.presentation)
nav_cols = st.columns([1.1, 1, 1, 1.35, 1.35, 1.3])
with nav_cols[0]:
    st.html('<div class="orb-nav-brand">ORB</div>')
for col, key, label in zip(nav_cols[1:], ('landing','prerace','live','ghost','demo'),
                           ('Overview','Forecast','Live Predictor','Ghost Strategy','Guided demo')):
    with col:
        st.page_link(PAGES[key], label=label)
with st.sidebar:
    with st.expander('More tools'):
        for key, label in (('decision','Decision board'),('feedback','Driver feedback'),('validation','Validation'),('generalisation','Generalisation')):
            st.page_link(PAGES[key], label=label)
if ctx is not None and nav.url_path:
    model_guide.route_badge(nav.url_path, ctx)
nav.run()
if ctx is not None:
    model_guide.route_help(nav.url_path, ctx)
