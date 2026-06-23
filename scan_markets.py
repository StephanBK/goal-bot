"""
scan_markets.py  —  Phase 2: the bot's "eyes".

Pulls every market in the World Cup team-total-goals series, parses each one
into (team, goal threshold, prices), and surfaces the cheap-NO candidates.

NOTE: reading market PRICES needs no API key and no money. Only PLACING orders
(a later phase) needs your signed Kalshi key. So this file is 100% read-only/safe.

Run it on a machine with open internet (your laptop or the Railway/Hetzner box):
    pip install requests
    python scan_markets.py
"""

import re
import time
import urllib.request
import urllib.parse
import json

# ---- Config (matches your locked settings) -------------------------------
BASE = "https://api.kalshi.com/trade-api/v2"
SERIES = "KXWCTEAMTOTALGOALS"
MAX_NO_PRICE = 20      # never look at NO offers above 20 cents
MIN_VOLUME = 0         # set >0 later to skip dead markets

# Regex that splits a market ticker like KXWCTEAMTOTALGOALS-26GER-11
# into: year=26, team=GER, threshold=11
TICKER_RE = re.compile(rf"{SERIES}-(\d{{2}})([A-Z]+)-(\d+)$")


def http_get(path, params):
    """Plain GET against Kalshi's public API. Returns parsed JSON."""
    url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "goal-bot/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_all_markets():
    """
    Page through every open market in the series.
    Kalshi returns results in pages; 'cursor' points to the next page.
    We loop until there's no cursor left.
    """
    markets, cursor = [], None
    while True:
        params = {"series_ticker": SERIES, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        data = http_get("/markets", params)
        markets.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)  # be polite to the rate limiter
    return markets


def parse_market(m):
    """
    Turn one raw Kalshi market dict into a tidy row.
    Prices on Kalshi are integer cents. no_ask = what you'd PAY to buy NO now.
    Returns None if the ticker doesn't match our series shape.
    """
    match = TICKER_RE.match(m.get("ticker", ""))
    if not match:
        return None
    year, team, threshold = match.group(1), match.group(2), int(match.group(3))
    return {
        "ticker":    m["ticker"],
        "team":      team,
        "threshold": threshold,          # "scores >= this many goals"
        "no_ask":    m.get("no_ask"),    # cents to BUY NO right now (taker)
        "no_bid":    m.get("no_bid"),    # cents someone will BUY NO from you
        "yes_ask":   m.get("yes_ask"),
        "volume":    m.get("volume", 0),
        "open_int":  m.get("open_interest", 0),
    }


def find_cheap_no(rows):
    """Keep only lines where NO is genuinely cheap and tradable."""
    out = []
    for r in rows:
        ask = r["no_ask"]
        if ask is None:
            continue
        if 1 <= ask <= MAX_NO_PRICE and r["volume"] >= MIN_VOLUME:
            out.append(r)
    # cheapest NO first, then by team
    out.sort(key=lambda r: (r["no_ask"], r["team"], r["threshold"]))
    return out


def main():
    print(f"Fetching series {SERIES} ...")
    raw = fetch_all_markets()
    rows = [p for m in raw if (p := parse_market(m))]
    print(f"  {len(raw)} raw markets -> {len(rows)} parsed lines "
          f"across {len(set(r['team'] for r in rows))} teams")

    cheap = find_cheap_no(rows)
    print(f"\nCheap-NO candidates (NO <= {MAX_NO_PRICE}c): {len(cheap)}\n")
    print(f"{'TEAM':<5}{'LINE':>6}{'NO_ask':>8}{'NO_bid':>8}{'Vol':>8}   ticker")
    print("-" * 60)
    for r in cheap:
        print(f"{r['team']:<5}{r['threshold']:>5}+{r['no_ask']:>7}c"
              f"{r['no_bid'] if r['no_bid'] is not None else '-':>8}"
              f"{r['volume']:>8}   {r['ticker']}")


if __name__ == "__main__":
    main()
