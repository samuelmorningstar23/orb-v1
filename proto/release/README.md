# Orb v1 build control

All commands run from `proto/` with the project python (`../.venv/bin/python`). Workstream 9 writes only
`progress/`, `checkpoints/`, `release/`, `tests/release/` and `build_control.py`.

## Commands

| Command | What it does |
|---|---|
| `python build_control.py status` | Heartbeat table: stale (> 40 min) -> AMBER, missing active workstream -> MISSING, blockers, merge-queue state, STOP_THE_LINE in red, last checkpoint, last green. `--json` for machines, `--no-color` for logs. |
| `release/run_checkpoint.sh Cn [DECISION] [note]` | Freezes the merge queue, runs the integration checks in order (schema validation, pytest, ownership audit, lock/dashboard consistency probe, sealed-holdout integrity), writes `checkpoints/Cn/{checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/*.txt, run_checkpoint.txt}` (text, not .log, because the repo ignores *.log), unfreezes on GO. |
| `python build_control.py checkpoint Cn DECISION [note]` | Same, without the shell wrapper. DECISION: `GO`, `GO_WITH_REASSIGNMENT`, `ROLLBACK`, `CUT_FROM_DEMO`, `HOLD`, `AUTO`, `REHEARSAL`. |
| `python build_control.py decide Cn DECISION [note]` | Finalise a `PENDING` (AUTO) checkpoint without re-running checks. Exit 0 on GO, 2 otherwise. |
| `python build_control.py sign Cn "name"` | Reviewer signature on the checkpoint report (roadmap 14.4). |
| `python build_control.py checks` | Run the integration checks only; nothing written. |
| `python build_control.py stop-the-line "reason" [--by "workstream 7"]` | Writes `release/STOP_THE_LINE.json`, freezes the queue; `status` shows it in red until `clear-stop`. |
| `python build_control.py clear-stop [note]` | Clears it (archived to `release/stop_history.jsonl`) and opens the queue. |
| `python build_control.py freeze [reason]` / `unfreeze [note]` | Manual merge-queue control (`release/merge_queue.json`). |
| `python build_control.py rollback --dry-run` | Last green commit, worktree plan and diff summary; nothing changed. |
| `release/rollback.sh` | Detached git worktree of the last green commit at `/private/tmp/orbv1_last_green` plus the diff summary; the main working tree is never touched. `--drill` also verifies `proto/out/lock.json` parses there, then removes the worktree. `--remove` cleans up. |
| `python build_control.py heartbeat '{"task": "...", "status": "GREEN"}'` | Merge fields into `progress/workstream_9.json` and stamp `updated_at`. |
| `python build_control.py summary` | Write `progress/SUMMARY.md` (traffic-light table and notes for the lead). |
| `python build_control.py active-workstreams 1 6 9` / `auto` | Override or restore the wave-derived set of workstreams expected to heartbeat (waves: 1 6 9; 2 4 8 from C1 GO; 3 5 7 from C2 GO). |
| `python release/ownership_audit.py [--strict] [--paths ...]` | Map changed paths to owning workstreams; flag unowned and lead-only paths. JSON out. |

## Decisions and the merge queue

* `GO` / `GO_WITH_REASSIGNMENT`: `checkpoints/last_green.json` is updated to the current commit, queue `OPEN`.
* `ROLLBACK`, `CUT_FROM_DEMO`, `HOLD`: recorded, queue stays `FROZEN` until a later GO.
* `AUTO` (default of `run_checkpoint.sh`): checks only. The record says `PENDING` with `proposed` GO or HOLD;
  the queue stays FROZEN until the lead runs `decide`. No automated GO ever updates the last-green registry.
* `REHEARSAL`: full artifact set under `checkpoints/rehearsal/Cn/`; queue and last green untouched.
* A green decision on failed checks is allowed (lead's call) but recorded as `decision_overrides_checks: true`
  and printed as a warning.

Check statuses: `PASS`, `FAIL` (blocks a proposed GO), `WARN` (ownership flags; does not block), `SKIP`
(input missing, with a note), `NOT_IMPLEMENTED` (consistency probe until Workstream 7 provides
`evaluation/red_team/consistency_probe.py`, exit 0 = lock and dashboard agree).

`artifact_hashes.json` records sha256[:16] of `out/lock.json`, `out/lock_v2.json`, the sealed holdout manifest and
its sidecar, the lock v2 fixture, the minimal schema, `ui/tokens.py` and `theme/base.css`; `checkpoint.md` marks what
changed since the last green. A changed sealed-holdout manifest fails `sealed_holdout_integrity` (stop-the-line
condition 1) until the lead confirms with an explicit decision.

## Ownership map (release/ownership_audit.py; lead decisions 12 Sep 14:55 and 15:05)

| Owner | Paths under proto/ |
|---|---|
| Workstream 1 | schemas/, fixtures/, validators/, shared/, tests/contract/, tests/conftest.py, out/lock_v2.json, out/lock_v2_sidecars/ |
| Workstream 2 | counterfactual/, events/, out/counterfactual/, tests/counterfactual/ |
| Workstream 3 | evaluation/ (except the sealed manifest pair), out/validation/, tests/evaluation/ |
| Workstream 4 | replay/, dashboard/components/, out/maps/, app_v2/components/race_twin/, tests/replay/ |
| Workstream 5 | interaction/ |
| Workstream 6 | app_v2/ (except components/race_twin/), ui/, theme/, views/, tests/ui/, tests/screenshots/ |
| Workstream 7 | evaluation/red_team/, tests/red_team/ |
| Workstream 8 | live/, decision/, out/live/, tests/live/ |
| Workstream 9 | progress/ (each workstream's own workstream_N.json is attributed to workstream N), checkpoints/, release/, tests/release/, build_control.py |
| Lead only (flagged when changed) | app.py, pipeline.py, model_v2.py, strategy2.py, liquid.py, refresh.sh, cleanup_pass.sh, extract_*.py, build_*.py (not build_control.py), refresh*.log, out/lock.json, out/*.pptx, out/*.pdf, evaluation/holdout/sealed_holdout_manifest.json and .sha256 |

Anything else (other out/ files, repository-root paths) is reported as unowned for the lead to confirm.

## Hidden build-control route

    cd proto && ../.venv/bin/streamlit run release/build_control_app.py --server.port 8599 --server.headless true

Open http://localhost:8599. Read-only; shows the heartbeat table, last checkpoint, merge queue, STOP_THE_LINE and the
last green commit. Not linked from the product dashboard.

## Heartbeat discipline

Every workstream writes `progress/workstream_N.json` every 30 minutes (schema in `progress/README.md`). Workstream 9 refreshes
`progress/SUMMARY.md` at the same cadence; missing or stale heartbeats are listed there for the lead, who pings the
workstream (Workstream 9 cannot message other workstreams).
