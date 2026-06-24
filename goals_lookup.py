"""
goals_lookup.py
---------------
Fetches real banked goals for every World Cup 2026 team from the
openfootball/worldcup.json public dataset (no API key, updated ~daily).

Usage:
    from goals_lookup import get_banked_goals
    banked = get_banked_goals()   # returns dict like {"GER": 9, "NED": 8, ...}
    goals  = banked.get("GER", 0)

The function caches the result in memory for CACHE_TTL seconds so the
bot's 2-second poll loop doesn't hammer GitHub on every cycle.
"""

import urllib.request
import json
import time
import logging

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# Refresh at most once per hour — the source is updated ~once/day
CACHE_TTL = 3600  # seconds

# openfootball uses full English team names; Kalshi uses ISO-3166 alpha-3.
# Add more entries here if new teams appear in goal-line markets.
NAME_TO_ISO = {
    # Group A
    "Mexico":           "MEX",
    "South Africa":     "ZAF",
    "South Korea":      "KOR",
    "Czech Republic":   "CZE",
    # Group B
    "Canada":           "CAN",
    "Bosnia & Herzegovina": "BIH",
    "Qatar":            "QAT",
    "Switzerland":      "SUI",
    # Group C
    "Brazil":           "BRA",
    "Morocco":          "MAR",
    "Haiti":            "HAI",
    "Scotland":         "SCO",
    # Group D
    "USA":              "USA",
    "Paraguay":         "PAR",
    "Australia":        "AUS",
    "Turkey":           "TUR",
    # Group E
    "Germany":          "GER",
    "Curaçao":          "CUW",
    "Ivory Coast":      "CIV",
    "Ecuador":          "ECU",
    # Group F
    "Netherlands":      "NED",
    "Japan":            "JPN",
    "Sweden":           "SWE",
    "Tunisia":          "TUN",
    # Group G
    "Belgium":          "BEL",
    "Egypt":            "EGY",
    "Iran":             "IRN",
    "New Zealand":      "NZL",
    # Group H
    "Spain":            "ESP",
    "Cape Verde":       "CPV",
    "Saudi Arabia":     "KSA",
    "Uruguay":          "URU",
    # Group I
    "France":           "FRA",
    "Senegal":          "SEN",
    "Iraq":             "IRQ",
    "Norway":           "NOR",
    # Group J
    "Argentina":        "ARG",
    "Algeria":          "DZA",
    "Austria":          "AUT",
    "Jordan":           "JOR",
    # Group K
    "Portugal":         "POR",
    "DR Congo":         "COD",
    "Uzbekistan":       "UZB",
    "Colombia":         "COL",
    # Group L
    "England":          "ENG",
    "Croatia":          "CRO",
    "Ghana":            "GHA",
    "Panama":           "PAN",
}

# ── Cache state ───────────────────────────────────────────────────────────────

_cache: dict[str, int] = {}
_cache_ts: float = 0.0


# ── Core logic ────────────────────────────────────────────────────────────────

def _count_team_goals(matches: list, team_name: str) -> int:
    """
    Sum goals scored BY `team_name` across all finished matches.

    Each match looks like:
        {
          "team1": "Germany",
          "team2": "Curaçao",
          "score": {"ft": [7, 1], "ht": [3, 1]},   # only present if finished
          ...
        }

    We use the final-time score ("ft") rather than counting goal objects,
    because own-goals are counted in the score but credited to the wrong
    side in the goals1/goals2 lists (own-goals count for the other team).
    """
    total = 0
    for m in matches:
        if "score" not in m:
            continue  # match not yet played
        ft = m["score"].get("ft")
        if ft is None or len(ft) != 2:
            continue
        if m.get("team1") == team_name:
            total += ft[0]
        elif m.get("team2") == team_name:
            total += ft[1]
    return total


def get_banked_goals(force_refresh: bool = False) -> dict[str, int]:
    """
    Returns a dict mapping ISO-3166 alpha-3 code → goals scored so far.
    Example: {"GER": 9, "NED": 8, "USA": 6, ...}

    Uses an in-process cache (CACHE_TTL seconds).  Pass force_refresh=True
    to bypass the cache (useful in tests or one-off scripts).
    """
    global _cache, _cache_ts

    now = time.time()
    if not force_refresh and _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache

    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "goal-bot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        logger.warning("goals_lookup: fetch failed (%s) — returning stale cache", exc)
        return _cache  # return whatever we had; don't crash the bot

    matches = data.get("matches", [])

    result: dict[str, int] = {}
    for name, iso in NAME_TO_ISO.items():
        result[iso] = _count_team_goals(matches, name)

    _cache = result
    _cache_ts = now
    logger.info("goals_lookup: refreshed — %d teams, sample GER=%d NED=%d USA=%d",
                len(result), result.get("GER", -1), result.get("NED", -1), result.get("USA", -1))
    return result


# ── Quick self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    goals = get_banked_goals(force_refresh=True)
    print("\nBanked goals per team (from openfootball live JSON):\n")
    for iso, g in sorted(goals.items(), key=lambda x: -x[1]):
        if g > 0:
            print(f"  {iso:4s}  {g}")
    print(f"\n  (teams with 0 goals not shown; {len(goals)} total teams tracked)")
