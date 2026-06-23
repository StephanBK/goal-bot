"""
pipeline.py  —  live wiring, Kalshi-native and mid-tournament aware.

Reads two SEPARATE Kalshi markets and trades their disagreement:
  KXWCSTAGEOFELIM   -> how far each team goes (a probability distribution)
  KXWCTEAMTOTALGOALS -> the goal ladder + NO prices

Mid-tournament facts are inferred from Kalshi itself (no outside data):
  banked goals  = (lowest still-open goal line) - 1
  games played  = derived from the earliest stage still open for that team

Zero dependencies. Read-only. Run:  python3 pipeline.py
"""

import re, time, urllib.request, urllib.parse, json
from datetime import datetime, timezone, timedelta
import model as M

BASE = "https://api.elections.kalshi.com/trade-api/v2"
STAGE_SERIES = "KXWCSTAGEOFELIM"
GOALS_SERIES = "KXWCTEAMTOTALGOALS"

MAX_NO_PRICE  = 20
MIN_NO_PRICE  = 3      # skip NO <=2c: at that price the market says it already happened
EDGE_MULT     = 2.0
MAX_PER_ORDER = 20.0
BANKROLL      = 100.0
DEFAULT_GPG   = 1.4
GPG = {"BRA":1.8,"ESP":1.8,"FRA":1.8,"ENG":1.7,"ARG":1.7,
       "GER":1.7,"POR":1.6,"NED":1.6,"USA":1.3}

# Live-match blacklist: never bet a team while it is playing.
MATCH_SERIES    = "KXWCGAME"
GAME_LEAD_MIN   = 30      # blacklist from 30 min before kickoff ...
GAME_TRAIL_MIN  = 30      # ... until 30 min after the final whistle
GAME_DURATION_H = 2.5     # kickoff estimated as expected_expiration_time - this
TEAM_ALIASES    = {}      # match-series code -> goals-series code (filled if mismatched)

# earliest stage still open -> games the team has already played
STAGE_ORDER = ["group","r32","r16","qf","sf","final","winner"]
GP_AT_ROUND = {"group":2,"r32":3,"r16":4,"qf":5,"sf":6,"final":7,"winner":8}


def fetch_series(series, status="open"):
    out, cursor = [], None
    while True:
        params = {"series_ticker": series, "limit": 1000}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        url = f"{BASE}/markets?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "goal-bot/0.3"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        out.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)
    return out


def d(m, key):
    v = m.get(key)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def team_of(t):
    m = re.search(r"-\d{2}([A-Z]{2,4})(?:-|$)", t or "")
    return m.group(1) if m else None


def threshold_of(m):
    thr = m.get("floor_strike")
    if thr is None:
        mt = re.search(r"-(\d+)$", m.get("ticker", ""))
        thr = int(mt.group(1)) if mt else None
    return int(thr) if thr is not None else None


def stage_key(label):
    l = (label or "").lower()
    if "group" in l: return "group"
    if "32" in l: return "r32"
    if "16" in l: return "r16"
    if "quarter" in l: return "qf"
    if "semi" in l: return "sf"
    if "win" in l or "champ" in l: return "winner"
    if "runner" in l or "final" in l: return "final"
    return None


def yes_prob(m):
    lp = d(m, "last_price_dollars")
    bid, ask = d(m, "yes_bid_dollars"), d(m, "yes_ask_dollars")
    if lp and lp > 0: return lp
    if bid is not None and ask is not None and ask > 0: return (bid + ask) / 2
    return ask


def build_stage_dist(stage_markets):
    dist = {}
    for m in stage_markets:
        team = team_of(m.get("ticker"))
        sk = stage_key(m.get("yes_sub_title") or m.get("title"))
        p = yes_prob(m)
        if team and sk and p:
            dist.setdefault(team, {})[sk] = p
    return dist


def build_goal_lines(goal_markets):
    lines = {}
    for m in goal_markets:
        team, thr, na = team_of(m.get("ticker")), threshold_of(m), d(m, "no_ask_dollars")
        if not (team and thr is not None and na is not None):
            continue
        lines.setdefault(team, []).append(
            {"threshold": thr, "no_ask": round(na * 100), "volume": d(m, "volume_fp") or 0,
             "ticker": m.get("ticker")})
    return lines


def infer_banked(ladders):
    """banked goals ~= (lowest still-open goal line) - 1."""
    return {team: max(min(l["threshold"] for l in lines) - 1, 0)
            for team, lines in ladders.items() if lines}


def games_played_for(team, stages):
    present = [s for s in STAGE_ORDER if s in stages.get(team, {})]
    return GP_AT_ROUND[present[0]] if present else 2


def two_teams(event_ticker):
    """KXWCGAME-26JUN22JORDZA -> ['JOR','DZA'] (the two 3-letter team codes)."""
    m = re.search(r"-\d{2}[A-Z]{3}\d{2}([A-Z]{6})$", event_ticker or "")
    if not m:
        return []
    s = m.group(1)
    return [s[:3], s[3:]]


def currently_playing_teams(match_markets, now=None):
    """Set of teams whose match window (kickoff-30m .. whistle+30m) contains now.
    expected_expiration_time sits at the final whistle; kickoff is estimated back
    from it. These teams are blacklisted so we never bet a side mid-game."""
    now = now or datetime.now(timezone.utc)
    busy, seen = set(), set()
    for m in match_markets:
        et = m.get("event_ticker")
        if et in seen:
            continue
        seen.add(et)
        ee = m.get("expected_expiration_time")
        if not ee:
            continue
        end = datetime.fromisoformat(ee.replace("Z", "+00:00"))
        start = end - timedelta(hours=GAME_DURATION_H)          # estimated kickoff
        if start - timedelta(minutes=GAME_LEAD_MIN) <= now <= end + timedelta(minutes=GAME_TRAIL_MIN):
            for t in two_teams(et):
                busy.add(TEAM_ALIASES.get(t, t))
    return busy


def analyze(stages, ladders, banked, playing=None):
    playing = playing or set()
    picks, diag = [], []
    for team, lines in ladders.items():
        sp = stages.get(team)
        if not sp or team in playing:        # no stage data, or team is mid-match
            continue
        g, bk, gp = GPG.get(team, DEFAULT_GPG), banked.get(team, 0), games_played_for(team, stages)
        low = min(lines, key=lambda l: l["threshold"])
        rlow = M.evaluate_line(low["threshold"], low["no_ask"], sp, g, banked=bk, games_played=gp,
                               max_price=99)  # always show the lowest line, even if >20c
        diag.append((team, bk, gp, low["threshold"], low["no_ask"], rlow["model_no_%"], rlow["price_%"]))
        for ln in lines:
            ask = ln["no_ask"]
            if ask is None or not (MIN_NO_PRICE <= ask <= MAX_NO_PRICE):
                continue
            r = M.evaluate_line(ln["threshold"], ask, sp, g, banked=bk, games_played=gp,
                                edge_mult=EDGE_MULT, max_price=MAX_NO_PRICE)
            if r["BUY"] == "YES":
                c = int((MAX_PER_ORDER * 100) // ask)
                picks.append({"ticker": ln["ticker"], "team": team, "line": ln["threshold"],
                              "no_ask": ask, "model_no": r["model_no_%"], "mkt_no": r["price_%"],
                              "edge_x": round(r["model_no_%"] / max(r["price_%"], 0.1), 2),
                              "cost": round(c * ask / 100, 2),
                              "banked": bk, "games_played": gp})
    picks.sort(key=lambda p: p["edge_x"], reverse=True)
    diag.sort()
    return picks, diag


def main():
    print("Fetching stage-of-elimination (open) ...")
    stages = build_stage_dist(fetch_series(STAGE_SERIES, "open"))
    print("Fetching goals ladder (open) ...")
    ladders = build_goal_lines(fetch_series(GOALS_SERIES, "open"))
    banked = infer_banked(ladders)

    picks, diag = analyze(stages, ladders, banked)

    print("\nPer-team inference (the brain's view of reality) — sample:")
    print(f"{'TEAM':<5}{'banked':>7}{'gms':>5}{'lowLine':>9}{'NO':>5}{'modelNO':>9}{'mktNO':>7}")
    print("-" * 47)
    for team, bk, gp, low, ask, mno, mkt in diag[:14]:
        print(f"{team:<5}{bk:>7}{gp:>5}{low:>8}+{ask:>4}c{mno:>8}%{mkt:>6}%")

    print(f"\nBuy candidates (NO<=20c, true>=2x price): {len(picks)}")
    for p in picks:
        print(f"  {p['team']} {p['line']}+ @ {p['no_ask']}c | model {p['model_no']}% vs {p['mkt_no']}% "
              f"| {p['edge_x']}x | ${p['cost']}")


if __name__ == "__main__":
    main()
