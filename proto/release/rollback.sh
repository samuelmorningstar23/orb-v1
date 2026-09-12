#!/usr/bin/env bash
# Orb v1 last-green rollback. Restores the last green build as a detached git worktree under
# /private/tmp/orbv1_last_green and prints the diff summary against the current working tree.
# The main working tree is NEVER checked out, reset or otherwise modified by this script.
#
#   release/rollback.sh              create (or recreate) the worktree and leave it in place
#   release/rollback.sh --dry-run    print commit, path and diff summary only
#   release/rollback.sh --drill      create, verify proto/out/lock.json parses inside it, then remove it (exit 0 = drill passed)
#   release/rollback.sh --remove     remove the worktree
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTO="$(dirname "$HERE")"
REPO="$(git -C "$PROTO" rev-parse --show-toplevel)"
PY="${ORB_PYTHON:-$REPO/.venv/bin/python}"; [ -x "$PY" ] || PY="$(command -v python3)"
WT="${ORB_LAST_GREEN_WORKTREE:-/private/tmp/orbv1_last_green}"
REG="$PROTO/checkpoints/last_green.json"
MODE=create
for a in "$@"; do
  case "$a" in
    --dry-run) MODE=dry ;; --drill) MODE=drill ;; --remove) MODE=remove ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 64 ;;
  esac
done

registered() { git -C "$REPO" worktree list --porcelain | grep -qx "worktree $WT"; }
remove_wt() {
  if registered; then git -C "$REPO" worktree remove --force "$WT"; echo "worktree removed: $WT"; fi
  git -C "$REPO" worktree prune
  if [ -d "$WT" ]; then
    if [ -z "$(ls -A "$WT")" ]; then rmdir "$WT"; else echo "ERROR: $WT exists, is not a registered worktree and is not empty; remove it by hand" >&2; return 1; fi
  fi
}

if [ "$MODE" = remove ]; then remove_wt; exit 0; fi
[ -f "$REG" ] || { echo "ERROR: $REG missing; no last green recorded" >&2; exit 1; }
SHORT="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_commit"])' "$REG")"
CP="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("checkpoint","?"))' "$REG")"
SHA="$(git -C "$REPO" rev-parse --verify --quiet "${SHORT}^{commit}")" || { echo "ERROR: last green commit $SHORT not found in $REPO" >&2; exit 1; }
echo "last green: $CP at $SHORT ($SHA)"
echo "worktree:   $WT ($( [ -d "$WT" ] && echo exists || echo absent ))"
echo "--- diff summary: working tree vs last green (tracked files) ---"
git -C "$REPO" diff --stat=110 "$SHA" | tail -n 60 || true
[ -n "$(git -C "$REPO" diff --stat "$SHA")" ] || echo "(no tracked differences)"
echo "untracked files not in last green: $(git -C "$REPO" ls-files --others --exclude-standard | wc -l | tr -d ' ')"
if [ "$MODE" = dry ]; then echo "--- dry run: nothing created ---"; exit 0; fi

remove_wt
git -C "$REPO" worktree add --detach "$WT" "$SHA" >/dev/null
HEAD_WT="$(git -C "$WT" rev-parse HEAD)"
[ "$HEAD_WT" = "$SHA" ] || { echo "ERROR: worktree HEAD $HEAD_WT != $SHA" >&2; exit 1; }
echo "worktree created at $WT (detached at $SHORT)"

if [ "$MODE" = drill ]; then
  RC=0
  if (cd "$WT" && "$PY" -c "import json; json.load(open('proto/out/lock.json'))"); then
    echo "drill: proto/out/lock.json parses in the last-green worktree: PASS"
  else
    echo "drill: proto/out/lock.json parse FAILED in the last-green worktree"; RC=1
  fi
  H_WT="$(shasum -a 256 "$WT/proto/out/lock.json" | cut -c1-16)"
  H_REG="$("$PY" -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("out/lock.json",""))
except Exception: print("")' "$PROTO/checkpoints/$CP/artifact_hashes.json")"
  if [ -n "$H_REG" ]; then
    [ "$H_WT" = "$H_REG" ] && echo "drill: lock.json hash $H_WT matches $CP artifact_hashes.json" || echo "drill: WARN lock.json hash $H_WT differs from $CP record $H_REG (checkpoint taken from an uncommitted lock?)"
  fi
  remove_wt
  [ "$RC" = 0 ] && echo "ROLLBACK DRILL PASSED ($CP at $SHORT)" || echo "ROLLBACK DRILL FAILED"
  exit "$RC"
fi

cat <<EOF
--- last green build ready ---
run it:      cd "$WT/proto" && "$REPO/.venv/bin/streamlit" run app.py
inspect:     git -C "$REPO" diff --stat $SHORT
promote it (LEAD ONLY, rewrites the main working tree):  git -C "$REPO" checkout $SHORT -- proto   # or: git reset --hard $SHORT
remove:      release/rollback.sh --remove
EOF
