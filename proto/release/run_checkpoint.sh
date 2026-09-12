#!/usr/bin/env bash
# Orb v1 checkpoint runner.   release/run_checkpoint.sh Cn [DECISION] [note]
#   1. freezes the merge queue (release/merge_queue.json state FROZEN)
#   2. runs, in order, capturing output to checkpoints/Cn/run_checkpoint.txt and checkpoints/Cn/logs/*.txt:
#        schema validation (validators/validate_lock.py out/lock_v2.json, skipped with a note if either is missing)
#        pytest tests -q (every test directory present)
#        ownership audit (release/ownership_audit.py)
#        lock/dashboard consistency probe (NOT_IMPLEMENTED until Workstream 7 provides evaluation/red_team/consistency_probe.py)
#        sealed holdout integrity (manifest vs .sha256 sidecar vs last green)
#   3. writes checkpoints/Cn/{checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json}
#   4. unfreezes the queue and updates checkpoints/last_green.json only on GO / GO_WITH_REASSIGNMENT.
# DECISION defaults to AUTO: the checks run and the record is PENDING with a proposed decision; the queue stays
# FROZEN until the lead runs `python build_control.py decide Cn GO 'note'`. REHEARSAL writes the full artifact
# set under checkpoints/rehearsal/Cn/ and changes no state. Exit: 0 GO, 3 PENDING, 2 other decision, 64 usage.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTO="$(dirname "$HERE")"
cd "$PROTO"
PY="${ORB_PYTHON:-$PROTO/../.venv/bin/python}"; [ -x "$PY" ] || PY="$(command -v python3)"
CN="${1:-}"; DECISION="${2:-AUTO}"; NOTE="${3:-}"
[[ "$CN" =~ ^C[0-9]+$ ]] || { echo "usage: release/run_checkpoint.sh Cn [GO|GO_WITH_REASSIGNMENT|ROLLBACK|CUT_FROM_DEMO|HOLD|AUTO|REHEARSAL] [note]" >&2; exit 64; }
DEC_UP="$(echo "$DECISION" | tr '[:lower:]' '[:upper:]')"
if [ "$DEC_UP" = REHEARSAL ]; then CDIR="checkpoints/rehearsal/$CN"; else CDIR="checkpoints/$CN"; fi
mkdir -p "$CDIR"
LOG="$CDIR/run_checkpoint.txt"   # .txt: *.log is gitignored
{
  echo "== Orb v1 checkpoint $CN ($DEC_UP) started $(date '+%Y-%m-%dT%H:%M:%S') by $(whoami) in $PROTO =="
  echo "git: $(git rev-parse --abbrev-ref HEAD 2>/dev/null) @ $(git rev-parse --short HEAD 2>/dev/null), $(git status --porcelain --untracked-files=all 2>/dev/null | wc -l | tr -d ' ') uncommitted paths"
} | tee "$LOG"
if [ "$DEC_UP" != REHEARSAL ]; then "$PY" build_control.py freeze "checkpoint $CN in progress (run_checkpoint.sh)" 2>&1 | tee -a "$LOG"; fi
"$PY" build_control.py checkpoint "$CN" "$DEC_UP" "$NOTE" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
{
  echo "== artifacts in $CDIR =="
  ls -1 "$CDIR" | sed 's/^/   /'
  echo "== merge queue: $("$PY" -c 'import build_control as bc; q=bc.get_queue(); print(q["state"], "-", q["reason"])' 2>/dev/null || echo unknown) =="
  echo "== checkpoint $CN finished $(date '+%Y-%m-%dT%H:%M:%S') exit $RC =="
} | tee -a "$LOG"
exit "$RC"
