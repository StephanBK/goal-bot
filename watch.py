"""
watch.py  —  the 24/7 sentry.

Each cycle:
  1. sweep Kalshi (stage + goals, open)        -> find cheap-NO candidates
  2. log any NEW candidate as a paper bet       -> tracker.record_flags
  3. sweep settled goals, grade open paper bets -> tracker.grade
  4. save the ledger + print the scoreboard
  5. sleep, repeat

Reads are free, so we poll fast. A full sweep is ~3 requests, so even a few
seconds between cycles stays far under Kalshi's rate limit.

    python3 watch.py          # loop forever (deploy mode)
    python3 watch.py --once    # a single cycle (for testing)
"""

import sys
import os
import time
import pipeline as P
import tracker as T

POLL_SECONDS = 2          # fast. WebSocket = the v2 for sub-second, when we go live.
STAKE = 20.0              # notional $ per paper bet (no real money)
# Local default; on Railway set PAPER_LOG_PATH=/data/paper_log.json (the volume).
LOG_PATH = os.environ.get("PAPER_LOG_PATH", "paper_log.json")


def build_resolution(settled_goal_markets):
    """ticker -> {status, result} so the grader knows which lines settled."""
    return {m.get("ticker"): {"status": m.get("status"), "result": m.get("result")}
            for m in settled_goal_markets}


def one_cycle(log):
    stages = P.build_stage_dist(P.fetch_series(P.STAGE_SERIES, "open"))
    ladders = P.build_goal_lines(P.fetch_series(P.GOALS_SERIES, "open"))
    banked = P.infer_banked(ladders)
    playing = P.currently_playing_teams(P.fetch_series(P.MATCH_SERIES, "open"))
    picks, _ = P.analyze(stages, ladders, banked, playing=playing)

    added = T.record_flags(log, picks, stake=STAKE)
    resolution = build_resolution(P.fetch_series(P.GOALS_SERIES, "settled"))
    graded = T.grade(log, resolution)
    T.save_log(LOG_PATH, log)
    return added, graded, picks


def main():
    once = "--once" in sys.argv
    log = T.load_log(LOG_PATH)
    cycle = 0
    while True:
        cycle += 1
        try:
            added, graded, picks = one_cycle(log)
            s = T.summary(log)
            print(f"[cycle {cycle}] candidates now: {len(picks)} | +{added} newly logged | "
                  f"{len(graded)} graded")
            print(f"           ledger: open {s['open']} | W {s['won']} L {s['lost']} | "
                  f"P&L ${s['pnl_$']} on ${s['staked_$']} ({s['roi_%']}% ROI)")
        except Exception as e:
            print(f"[cycle {cycle}] error: {e}")
        if once:
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
