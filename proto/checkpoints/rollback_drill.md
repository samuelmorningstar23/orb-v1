# Rollback drill (task 0.16)

Run at 2026-09-12 14:51 local with `release/rollback.sh --drill` from `proto/`. Result: **PASSED**.

What the drill does: reads `checkpoints/last_green.json`, resolves the commit, adds a detached git worktree of it at
`/private/tmp/orbv1_last_green`, prints the diff summary against the current working tree, verifies inside the
worktree that `python -c "import json; json.load(open('proto/out/lock.json'))"` succeeds, compares the lock hash with
the checkpoint's `artifact_hashes.json`, then removes the worktree and prunes. The main working tree is never
checked out, reset or modified.

## Captured output

```
last green: C0 at 02f4c00 (02f4c0052f22dfcc957ba2210849a5f3cd26975e)
worktree:   /private/tmp/orbv1_last_green (absent)
--- diff summary: working tree vs last green (tracked files) ---
 proto/build_control.py                    | 792 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++--
 proto/checkpoints/C0/artifact_hashes.json |   4 +-
 proto/checkpoints/C0/checkpoint.json      |  10 +-
 proto/checkpoints/C0/checkpoint.md        |   8 +-
 proto/checkpoints/last_green.json         |   4 +-
 5 files changed, 787 insertions(+), 31 deletions(-)
untracked files not in last green: 28
Preparing worktree (detached HEAD 02f4c00)
worktree created at /private/tmp/orbv1_last_green (detached at 02f4c00)
drill: proto/out/lock.json parses in the last-green worktree: PASS
drill: lock.json hash 74fcbc9f6dd1f340 matches C0 artifact_hashes.json
worktree removed: /private/tmp/orbv1_last_green
ROLLBACK DRILL PASSED (C0 at 02f4c00)
```

After the drill: `git worktree list` shows only the main tree; `/private/tmp/orbv1_last_green` is gone.

## Restore in one command (non-drill)

    release/rollback.sh            # worktree of the last green at /private/tmp/orbv1_last_green, left in place
    cd /private/tmp/orbv1_last_green/proto && ../../../Users/samuelmorningstar/Trackshift/.venv/bin/streamlit run app.py

Promoting the last green into the main working tree is a lead-only action (`git checkout <sha> -- proto` or
`git reset --hard <sha>`); the script prints the exact command and does not run it.

## Notes

* `last_green.json` records a commit, so a rollback restores committed state only. Uncommitted work at the time of
  a GO is not covered; the lead commits at every checkpoint (roadmap 14.1).
* `--dry-run` (`python build_control.py rollback --dry-run`) prints the same summary without creating anything.
* Repeat the drill after every GO that moves `last_green.json`; it takes about two seconds.
