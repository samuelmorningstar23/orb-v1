"""Hidden build-control route. Read-only view of heartbeats, last checkpoint, merge queue,
STOP_THE_LINE and the last green commit. Not linked from the product dashboard.

Launch from proto/:
    ../.venv/bin/streamlit run release/build_control_app.py --server.port 8599 --server.headless true
then open http://localhost:8599
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent
sys.path.insert(0, str(PROTO))

import streamlit as st  # noqa: E402

import build_control as bc  # noqa: E402

st.set_page_config(page_title='Orb v1 build control', layout='wide')
st.title('Orb v1 build control (hidden route, Workstream 9)')
st.caption(f'proto: {PROTO}   |   launch: ../.venv/bin/streamlit run release/build_control_app.py --server.port 8599 --server.headless true')

rep = bc.status_report(PROTO)
stop = rep['stop']
if stop:
    st.error(f"STOP THE LINE since {stop.get('at')} by {stop.get('by')}: {stop.get('reason')}    (clear: python build_control.py clear-stop)")
else:
    st.success('No stop-the-line active')

q, lc, lg = rep['queue'], rep['last_checkpoint'], rep['last_green']
c1, c2, c3 = st.columns(3)
with c1:
    st.subheader('Merge queue')
    (st.warning if q.get('state') == 'FROZEN' else st.info)(f"{q.get('state')}: {q.get('reason')} (since {q.get('since') or '-'})")
with c2:
    st.subheader('Last checkpoint')
    if lc:
        st.write(f"**{lc['checkpoint']} {lc['decision']}**" + (f" (proposed {lc.get('proposed')})" if lc.get('decision') == 'PENDING' else ''))
        st.write(f"at {lc['at']}, commit `{lc['git_commit']}`, checks green: {lc.get('all_green')}")
    else:
        st.write('none recorded')
with c3:
    st.subheader('Last green')
    st.write(f"**{lg.get('checkpoint')}** commit `{lg.get('git_commit')}` at {lg.get('at')}" if lg else 'none')
    st.write(f"rollback: `release/rollback.sh --dry-run`, worktree at `{bc.WORKTREE}`")

st.subheader(f"Heartbeats (active workstreams {rep['active_workstreams']}; stale after {bc.STALE_MIN} min; now {rep['at']})")
rows = [dict(workstream=r['workstream'], status=r['effective'], age_min=r['age_min'], task=r['task'], tests=f"{r['tests_passed']}/{r['tests_passed'] + r['tests_failed']}",
             eta_min=r['eta_minutes'], blockers='; '.join(map(str, r['blockers'])), needs_review_from=', '.join(map(str, r['needs_review_from'])),
             updated_at=r['updated_at']) for r in rep['heartbeats']]
if rows:
    try:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except Exception:
        st.table(rows)
else:
    st.write('no heartbeats')
if rep['missing']:
    st.error(f"missing heartbeats: workstreams {rep['missing']}")
if rep['stale']:
    st.warning(f"stale heartbeats: workstreams {rep['stale']}")
if rep['blockers']:
    st.subheader('Blockers')
    for a, b in rep['blockers'].items():
        st.write(f"workstream {a}: {', '.join(map(str, b))}")

st.subheader('Checkpoints')
cps = []
for d in bc.checkpoint_dirs(PROTO):
    r = bc.read_json(d / 'checkpoint.json') or {}
    cps.append(dict(checkpoint=r.get('checkpoint', d.name), decision=r.get('decision'), at=r.get('at'), commit=r.get('git_commit'),
                    checks_green=r.get('all_green'), decided_by=r.get('decided_by'), signed_by=r.get('signed_by')))
st.table(cps) if cps else st.write('none')

with st.expander('raw status JSON'):
    st.code(json.dumps(rep, indent=1, default=str), language='json')
if st.button('Refresh'):
    st.rerun()
