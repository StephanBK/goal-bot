"""
pipeline.py  —  Phase 3 steps 2-4: the live wiring.

For every team it:
  1. reads KXWCSTAGEOFELIM  -> how far the team goes (a probability distribution)
  2. reads KXWCTEAMTOTALGOALS -> the cheap-NO goal ladder + prices
  3. joins them by team code, runs model.py, applies your 2x / <=20c filter
  4. prints a ranked list of real buy candidates with suggested sizing

Zero dependencies (uses Python's built-in urllib). Read-only: it places NO orders.
Run on any machine with open internet:
    python pipeline.py
"""

import re
import time
import math
import urllib.request
import urllib.parse
import json

import model as M

BASE = "https://api.kalshi.com/trade-api/v2"
STAGE_SERIES = "KXWCSTAGEOFELIM"
GOALS_SERIES = "KXWCTEAMTOTALGOALS"

# --- Settings (your locked config) ---------------------------------------
MAX_NO_PRICE = 20     # never pay more than 20c for NO
EDGE_MULT    = 2.0    # true NO prob must be >= 2x the price
MAX_PER_ORDER = 20.0  # dollars per order
BANKROLL = 100.0      # total to deploy, then stop

# Goals-per-game prior. Flat default + a few overrides. Advancement does most
# of the work; this gets calibrated from Kalshi match markets in a later step.
DEFAULT_GPG = 1.4
GPG = {"BRA": 1.8, "ESP": 1.8, "FRA": 1.8, "ENG": 1.7, "ARG": 1.7,
       "GER": 1.7, "POR": 1.6, "NED": 1.6, "USA": 1.3}


# --- Tiny Kalshi reader ---------------------------------------------------
def fetch_series(series):
    """Page through every open market in a series."""
    out, cursor = [], None
    while True:
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        url = f"{BASE}/markets?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "goal-bot/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        out.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)
    return out


def team_of(ticker):
    """KXWCSTAGEOFELIM-26GER-...  ->  'GER'"""
    m = re.search(r"-\d{2}([A-Z]{2,4})(?:-|$)", ticker or "")
    return m.group(1) if m else None


def stage_key(label):
    """Map a human stage label to our games-played buckets. Order matters:
    check 'quarter'/'semi' before 'final' so 'semifinal' isn't misread."""
    l = (label or "").lower()
    if "group" in l:                      return "group"
    if "32" in l:                         return "r32"
    if "16" in l:                         return "r16"
    if "quarter" in l:                    return "qf"
    if "semi" in l:                       return "sf"
    if "win" in l or "champ" in l:        return "winner"
    if "runner" in l or "final" in l:     return "final"
    return None


def yes_prob(m):
    """Implied YES probability for a market (the chance it resolves yes)."""
    bid, ask = m.get("yes_bid"), m.get("yes_ask")
    if bid is not None and ask is not None and ask > 0:
        return (bid + ask) / 2 / 100.0
    lp = m.get("last_price")
    return (lp / 100.0) if lp else None


# --- Build the two halves -------------------------------------------------
def build_stage_dist(stage_markets):
    """{team: {stage: prob}} from the stage-of-elimination series."""
    dist = {}
    for m in stage_markets:
        team = team_of(m.get("ticker"))
        label = m.get("yes_sub_title") or m.get("subtitle") or m.get("title")
        sk = stage_key(label)
        p = yes_prob(m)
        if team and sk and p:
            dist.setdefault(team, {})[sk] = p
    return dist


def build_goal_lines(goal_markets):
    """{team: [ {threshold, no_ask, volume, ticker} ]} from the goals ladder."""
    lines = {}
    for m in goal_markets:
        t = m.get("ticker", "")
        mt = re.search(r"-\d{2}[A-Z]{2,4}-(\d+)$", t)
        team = team_of(t)
        if not (team and mt):
            continue
        lines.setdefault(team, []).append({
            "threshold": int(mt.group(1)),
            "no_ask": m.get("no_ask"),
            "volume": m.get("volume", 0),
            "ticker": t,
        })
    return lines


# --- The join + ranking ---------------------------------------------------
def analyze(stage_markets, goal_markets):
    stages = build_stage_dist(stage_markets)
    ladders = build_goal_lines(goal_markets)
    picks = []
    for team, lines in ladders.items():
        sp = stages.get(team)
        if not sp:
            continue                       # no advancement data -> skip
        g = GPG.get(team, DEFAULT_GPG)
        for ln in lines:
            ask = ln["no_ask"]
            if ask is None or not (1 <= ask <= MAX_NO_PRICE):
                continue
            r = M.evaluate_line(ln["threshold"], ask, sp, g,
                                edge_mult=EDGE_MULT, max_price=MAX_NO_PRICE)
            if r["BUY"] == "YES":
                contracts = int((MAX_PER_ORDER * 100) // ask)   # within $20/order
                picks.append({
                    "team": team, "line": ln["threshold"], "no_ask": ask,
                    "model_no": r["model_no_%"], "mkt_no": r["price_%"],
                    "edge_x": round(r["model_no_%"] / r["price_%"], 2),
                    "contracts": contracts, "cost": round(contracts * ask / 100, 2),
                    "ticker": ln["ticker"],
                })
    picks.sort(key=lambda p: p["edge_x"], reverse=True)   # best mispricing first
    return picks


def main():
    print("Fetching stage-of-elimination ...")
    stage_markets = fetch_series(STAGE_SERIES)
    print("Fetching goals ladder ...")
    goal_markets = fetch_series(GOALS_SERIES)
    picks = analyze(stage_markets, goal_markets)

    print(f"\nBuy candidates (NO<=20c, true>=2x price): {len(picks)}\n")
    print(f"{'TEAM':<5}{'LINE':>6}{'NO':>5}{'model':>8}{'mkt':>6}{'edge':>6}"
          f"{'qty':>6}{'cost':>8}")
    print("-" * 56)
    spent = 0.0
    for p in picks:
        flag = "" if spent + p["cost"] <= BANKROLL else "  (over $100)"
        if not flag:
            spent += p["cost"]
        print(f"{p['team']:<5}{p['line']:>5}+{p['no_ask']:>4}c{p['model_no']:>7}%"
              f"{p['mkt_no']:>5}%{p['edge_x']:>5}x{p['contracts']:>6}"
              f"{p['cost']:>7}${flag}")
    print(f"\nTotal to deploy within ${BANKROLL:.0f} cap: ${spent:.2f}")


if __name__ == "__main__":
    main()
