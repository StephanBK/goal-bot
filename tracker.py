"""
tracker.py  —  the paper-trade ledger (no real money).

Every time the screen flags a cheap-NO candidate, we record it here as a
*pretend* purchase. When that goal line later settles on Kalshi, we grade it:
  - NO wins  if the team fell SHORT of the line   (market result == "no")  -> pays $1/contract
  - NO loses if the team REACHED the line         (market result == "yes") -> worth $0

The running P&L is the whole point: it tells us, with real outcomes and zero
risk, whether the edge is real. State lives in a JSON file so it survives restarts.
"""

import json
import math
import os
from datetime import datetime, timezone


def kalshi_fee(contracts, price):
    """Kalshi trading fee = 0.07 * contracts * price * (1-price), rounded UP to the cent.
    Tiny at extreme prices (cheap NO), but real over many trades."""
    return math.ceil(0.07 * contracts * price * (1 - price) * 100) / 100


def load_log(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_log(path, log):
    with open(path, "w") as f:
        json.dump(log, f, indent=2)


def record_flags(log, flags, stake=20.0, now=None):
    """Add any NEW candidate as an open paper position (one per market ticker)."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    for f in flags:
        tk = f["ticker"]
        if tk in log:                      # already tracking this line, skip
            continue
        price = f["no_ask"] / 100.0
        contracts = round(stake / price) if price > 0 else 0
        log[tk] = {
            "ticker": tk, "team": f["team"], "line": f["line"],
            "entry_no_c": f["no_ask"], "model_no": f["model_no"], "mkt_no": f["mkt_no"],
            "edge_x": f["edge_x"], "stake": stake, "contracts": contracts,
            "entry_fee": kalshi_fee(contracts, price),
            "entry_time": now, "status": "open", "result": None, "pnl": None,
        }
        added += 1
    return added


def grade(log, resolution):
    """Score open positions whose market has settled.
    resolution = { ticker: {"status": "...", "result": "yes"|"no"|""} }"""
    newly = []
    for tk, rec in log.items():
        if rec["status"] != "open":
            continue
        info = resolution.get(tk)
        if not info:
            continue
        if info.get("status") not in ("settled", "finalized") or info.get("result") not in ("yes", "no"):
            continue
        price = rec["entry_no_c"] / 100.0
        if info["result"] == "no":                     # team fell short -> NO wins
            rec["pnl"] = round(rec["contracts"] * (1.0 - price) - rec["entry_fee"], 2)
            rec["status"] = "won"
        else:                                          # team reached line -> NO loses
            rec["pnl"] = round(-rec["contracts"] * price - rec["entry_fee"], 2)
            rec["status"] = "lost"
        rec["result"] = info["result"]
        newly.append(tk)
    return newly


def summary(log):
    won = [r for r in log.values() if r["status"] == "won"]
    lost = [r for r in log.values() if r["status"] == "lost"]
    settled = won + lost
    pnl = round(sum(r["pnl"] for r in settled), 2)
    staked = round(sum(r["stake"] for r in settled), 2)
    return {
        "open": sum(1 for r in log.values() if r["status"] == "open"),
        "won": len(won), "lost": len(lost), "settled": len(settled),
        "win_rate_%": round(100 * len(won) / len(settled), 1) if settled else 0.0,
        "pnl_$": pnl, "staked_$": staked,
        "roi_%": round(100 * pnl / staked, 1) if staked else 0.0,
    }
