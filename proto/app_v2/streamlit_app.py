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
from app_v2.ui import shell  # noqa: E402

PAGES = {
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
nav = st.navigation(list(PAGES.values()), position='top')
ctx = common.bootstrap()            # lock, query params, sidebar (engineering controls + presentation toggle)
shell.inject_css(ctx.presentation)
nav.run()
