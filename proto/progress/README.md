# Heartbeats (Workstream 9 collects every 30 minutes)
Each workstream writes progress/workstream_N.json:
{"workstream": 6, "task": "live_predictor_ui", "status": "GREEN|AMBER|RED", "commit": "...", "completed": [], "in_progress": [], "blockers": [], "tests_passed": 0, "tests_failed": 0, "eta_minutes": 0, "needs_review_from": [], "updated_at": "ISO time"}
Stale (> 40 min) heartbeats are flagged AMBER by build_control.py. Checkpoints live in checkpoints/Cn/.
