"""
scan_report.py  —  LANDSCAPE SURVEY (read-only, no betting, no money).

Answers one question: across every team, what NO goal-lines exist, how much
real money could I actually place at each, and which of our rules does each
line pass or fail?

Unlike the live bot (which only logs strict-rule winners), this shows the FULL
landscape so we can judge whether real opportunities exist at all:

  - every NO line at or below MAX_NO_PRICE, INCLUDING the 1-2c below-floor lines
  - real available liquidity from the Kalshi ORDER BOOK (not historical volume):
        contracts buyable + $ cost, at the quoted price AND within our band
  - the model edge for context (shown, never used to filter rows)
  - a RULES column tagging each line: price-band / edge / blacklist pass-fail

The blacklist IS respected for the "would the bot bet this" verdict, matching
your choice to keep it. Mid-match teams are shown but tagged BLACKLISTED.

Run:  python3 scan_report.py
"""

import urllib.request, urllib.parse, json, time
import pipeline as P
import model as M

ORDERBOOK_BAND_MAX = P.MAX_NO_PRICE   # only count buyable money up to our cap (20c)


def fetch_orderbook(ticker):
    """Return the NO side of the book as a list of (price_cents, contracts).
    The book is the live list of resting offers; this is REAL available money,
    unlike 'volume' which is just historical turnover."""
    url = f"{P.BASE}/markets/{urllib.parse.quote(ticker)}/orderbook"
    req = urllib.request.Request(url, headers={"User-Agent": "goal-bot/0.3"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        return []
    book = (data.get("orderbook_fp") or {}).get("no_dollars") or []
    out = []
    for row in book:
        try:
            price_c = round(float(row[0]) * 100)
            contracts = float(row[1])
            out.append((price_c, contracts))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def buyable_at_or_below(book, max_price_c):
    """Total contracts + $ available to BUY NO at price <= max_price_c.
    A buyer takes the cheapest offers first, so we sum every resting offer
    at or under our ceiling."""
    contracts = sum(q for pc, q in book if pc <= max_price_c)
    dollars = sum(q * pc / 100.0 for pc, q in book if pc <= max_price_c)
    return contracts, dollars


def main():
    print("Fetching markets (stage + goals + matches) ...")
    stages = P.build_stage_dist(P.fetch_series(P.STAGE_SERIES, "open"))
    ladders = P.build_goal_lines(P.fetch_series(P.GOALS_SERIES, "open"))
    banked = P.infer_banked(ladders)
    playing = P.currently_playing_teams(P.fetch_series(P.MATCH_SERIES, "open"))

    rows = []
    for team, lines in ladders.items():
        sp = stages.get(team)
        if not sp:
            continue
        gpg = P.GPG.get(team, P.DEFAULT_GPG)
        bk = banked.get(team, 0)
        gp = P.games_played_for(team, stages)
        is_blacklisted = team in playing
        for ln in sorted(lines, key=lambda x: x["threshold"]):
            ask = ln["no_ask"]
            if ask is None or ask > P.MAX_NO_PRICE:
                continue   # outside our price cap entirely; skip
            # model edge for context (not a filter)
            r = M.evaluate_line(ln["threshold"], ask, sp, gpg, banked=bk,
                                games_played=gp, edge_mult=P.EDGE_MULT,
                                max_price=P.MAX_NO_PRICE)
            # real available money from the order book
            book = fetch_orderbook(ln["ticker"])
            time.sleep(0.1)   # be polite to the API
            c_at_price, d_at_price = buyable_at_or_below(book, ask)
            c_in_band, d_in_band = buyable_at_or_below(book, ORDERBOOK_BAND_MAX)
            # rule tags
            below_floor = ask < P.MIN_NO_PRICE
            has_edge = r["BUY"] == "YES"
            tags = []
            if below_floor: tags.append("BELOW-FLOOR")
            if is_blacklisted: tags.append("BLACKLISTED")
            if has_edge and not below_floor and not is_blacklisted:
                tags.append("BOT-WOULD-BET")
            rows.append({
                "team": team, "line": ln["threshold"], "no_c": ask,
                "banked": bk, "gp": gp,
                "model_no": r["model_no_%"], "mkt_no": r["price_%"],
                "edge_x": round(r["model_no_%"] / max(r["price_%"], 0.1), 2),
                "c_at_price": c_at_price, "d_at_price": d_at_price,
                "c_in_band": c_in_band, "d_in_band": d_in_band,
                "tags": ",".join(tags) if tags else "-",
            })

    # sort: bot-would-bet first, then by edge
    rows.sort(key=lambda x: ("BOT-WOULD-BET" not in x["tags"], -x["edge_x"]))

    print(f"\nLANDSCAPE: {len(rows)} NO lines at <= {P.MAX_NO_PRICE}c "
          f"(floor {P.MIN_NO_PRICE}c, edge mult {P.EDGE_MULT}x)\n")
    hdr = (f"{'TEAM':<5}{'LINE':>5}{'NOc':>5}{'bank':>5}{'edge':>7}"
           f"{'$@price':>9}{'$<=20c':>9}  RULES")
    print(hdr)
    print("-" * len(hdr))
    for x in rows:
        print(f"{x['team']:<5}{str(x['line'])+'+':>5}{x['no_c']:>5}{x['banked']:>5}"
              f"{str(x['edge_x'])+'x':>7}"
              f"{'$'+format(x['d_at_price'],'.0f'):>9}{'$'+format(x['d_in_band'],'.0f'):>9}"
              f"  {x['tags']}")

    bot_bets = [x for x in rows if "BOT-WOULD-BET" in x["tags"]]
    print(f"\nSUMMARY")
    print(f"  total NO lines surveyed:      {len(rows)}")
    print(f"  bot-would-bet (all rules ok): {len(bot_bets)}")
    if bot_bets:
        tot = sum(x["d_at_price"] for x in bot_bets)
        print(f"  real $ buyable on those bets: ${tot:.0f}")
    blk = sum(1 for x in rows if "BLACKLISTED" in x["tags"])
    flr = sum(1 for x in rows if "BELOW-FLOOR" in x["tags"])
    print(f"  below-floor (1-2c) lines:     {flr}")
    print(f"  blacklisted (mid-match) lines:{blk}")


if __name__ == "__main__":
    main()
