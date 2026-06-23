# goal-bot — Handover / Resume File

_Last updated: 2026-06-23 (mid-2026 FIFA World Cup, group stage). Repo commit: `b9b2f63`._

---

## 1. TL;DR — read this first

**What it is:** a 24/7 *paper-trading screen* for Kalshi's World Cup "team total goals" markets. It buys nothing real. It watches the markets, flags cheap "NO" bets our model thinks are underpriced, logs each as a pretend bet, and grades it win/loss when the market settles — so we learn whether there's a real edge **at $0 risk**.

**The strategy:** buy a cheap **NO** on a "Team scores N+ goals" line (e.g. NO at 4¢) when our model says the true chance the team falls short is meaningfully higher than the price. Payoff is asymmetric — a 4¢ winner pays ~24× — so a longshot only needs to be slightly less long than the price implies.

**Status as of today:** **DEPLOYED AND LIVE.** Running 24/7 on Railway with a persistent volume. This was the big milestone this session — see §8 for what we did.

**Honest verdict so far:** still zero genuine edges, now *confirmed with live liquidity data*. Today's landscape scan found only 1 strict-rule candidate with **$3** of real money behind it (see §6). The screen keeps running to gather more evidence.

---

## 2. Where everything lives

| Thing | Location |
|---|---|
| GitHub repo | `github.com/StephanBK/goal-bot` (branch `main`, commit `b9b2f63`) |
| Local copy | `~/Downloads/bot` |
| Runtime | **LIVE** — Railway project `responsible-simplicity`, service `web`, env `production` |
| Railway volume | mounted at `/data`, holds `paper_log.json` (survives redeploys) |
| Railway env var | `PAPER_LOG_PATH=/data/paper_log.json` |
| Kalshi API base | `https://api.elections.kalshi.com/trade-api/v2` (read-only; no key needed) |

---

## 3. The files

| File | Role |
|---|---|
| `watch.py` | The 24/7 sentry loop Railway runs: sweep → flag → log → grade → repeat (every 2s). Entry point. |
| `pipeline.py` | Reads Kalshi, runs the model, applies all filters, returns ranked candidates. **Now also emits `banked` + `games_played` per pick.** |
| `model.py` | The probability brain. Turns advancement odds into `P(team finishes with < N goals)`. Pure math. |
| `tracker.py` | The paper-bet ledger. **Now records `banked_at_entry` + `games_played_at_entry` per bet.** Persists to JSON. |
| `scan_report.py` | **NEW this session.** Standalone landscape survey: every NO line ≤20¢, real orderbook liquidity ($ buyable), rule pass/fail tags. Read-only, never touches the bot. Run: `python3 scan_report.py`. |
| `Procfile` | One line — tells Railway to run `python watch.py`. |
| `requirements.txt` | Stdlib only; signals "Python project" to Railway. |
| `.gitignore` | **NEW this session.** Ignores `__pycache__/`, `*.pyc`, `paper_log.json`. |
| `scan_markets.py` | **Deprecated** v1 prototype. Can delete. |

---

## 4. How the model works (the brain)

> **how far a team advances → how many games it plays → how many goals it likely totals → P(it finishes under the line)**

- **Cross-market, not circular:** we price the *goals ladder* (`KXWCTEAMTOTALGOALS`) using Kalshi's *separate* advancement market (`KXWCSTAGEOFELIM`). Two markets → we trade their disagreement.
- **Mid-tournament aware:** adds **goals already banked**, rolls dice only over **remaining games**.
- **Math:** `P(goals ≥ N) = Σ over stages [ P(eliminated at stage) × P(Poisson(remaining_games × goals_per_game) ≥ N − banked) ]`.

---

## 5. Hard-won facts & gotchas

1. **The API moved.** `api.kalshi.com` is dead. Use `https://api.elections.kalshi.com/trade-api/v2`.
2. **Prices are dollar-strings now**, not integer cents: `"no_ask_dollars":"0.0400"` = 4¢. Goal line is in `floor_strike`.
3. **Order book ≠ volume.** `volume` is historical turnover; the **order book** (`/markets/{ticker}/orderbook`, `no_dollars` side) is the *real money available to buy right now*. `scan_report.py` uses the order book. This distinction is the whole point of today's scan — quoted prices lie, the book tells the truth.
4. **Kalshi-native inference:** `banked goals` ≈ (lowest still-open goal line) − 1; `games played` ⇐ earliest stage still open in `KXWCSTAGEOFELIM`.
5. **`expected_expiration_time` ≈ the final whistle** — use it to tell if a team is playing. `close_time` / `open_time` are red herrings.
6. **Team codes** are ISO, consistent across series (Algeria = `DZA` everywhere). No alias map needed.
7. **Stage → total games:** group 3, R32 4, R16 5, QF 6, SF/Final/Winner 8.
8. **Goal lines settle on ELIMINATION, not nightly.** A team's goal total only locks when they're knocked out. So W/L grades arrive slowly — don't expect settled bets day-to-day during the group stage.

---

## 6. What we learned (Jordan + today's liquidity finding)

**The Jordan lesson (earlier):** we flagged "Jordan 2+ NO" as a 5× edge; reality showed the market was right and our goals-Poisson was blind to the live fixture. Fixes built: a `≤2¢ floor` (skip NO that cheap — market says it already happened) and a `live-match blacklist` (never bet 30 min before kickoff → 30 min after whistle).

**Today's liquidity finding (the new one):** ran `scan_report.py` against live order books. Result:
- **5 total NO lines** ≤20¢ across all teams.
- **1** passed all strict rules: USA 12+ NO @ 3¢, "16.73× edge."
- BUT the order book showed only **$3 of real money** buyable on it. The deep liquidity (331 contracts) sat at **1¢** — i.e. the market saying USA already banked their 12 goals. The 3¢ "edge" is a mirage with no money behind it.
- Every other line: edge < 1× (model agrees with market) or below floor.

**The sober takeaway, now confirmed with real liquidity:** there is no tradeable edge right now. A huge edge-multiple on $3 of liquidity is noise, not opportunity. Wanting $20/bet but the book offering $3 = not a real market to trade.

---

## 7. Config (the locked parameters)

| Parameter | Value | Where |
|---|---|---|
| Side | Buy **NO** (cheap longshots) | — |
| Price band | **3¢ – 20¢** (`MIN_NO_PRICE=3`, `MAX_NO_PRICE=20`) | `pipeline.py` |
| Edge rule | model true NO ≥ **2× price** (`EDGE_MULT=2.0`) | `pipeline.py` |
| Live-match blacklist | 30 min before kickoff → 30 min after whistle | `pipeline.py` |
| Poll interval | every **2 s** | `watch.py` (`POLL_SECONDS`) |
| Paper stake | **$20** notional per bet | `watch.py` (`STAKE`) |
| Real bankroll (later) | $100 cap — NOT enforced yet, not live | — |
| Goals/game | per-team dict + **1.4 default** — UNCALIBRATED, known weakness | `pipeline.py` (`GPG`) |

---

## 8. What we did THIS session (2026-06-23)

1. **Deployed to Railway** (the milestone). Service `web` in project `responsible-simplicity`, env `production`. Worker, not web server — "no ports detected" is expected and fine.
2. **Attached a persistent Volume** at `/data` (via canvas → attach volume to `web`). Ledger survives redeploys here.
3. **Set env var** `PAPER_LOG_PATH=/data/paper_log.json`.
4. **Verified the sentry is alive** — logs scroll `[cycle N] candidates now: …` every ~2s. Confirmed online.
5. **Upgraded the ledger** — `pipeline.py` now emits `banked` + `games_played`; `tracker.py` now saves `banked_at_entry` + `games_played_at_entry`. (Existing open bet from before the change keeps its old record — no retroactive backfill.)
6. **Added `.gitignore`** + removed a stray committed `.pyc`.
7. **Built `scan_report.py`** — the landscape survey with real order-book liquidity. Ran it; got the §6 finding.
8. Pushes: `b1a3713` (ledger + gitignore), `b9b2f63` (scan_report).

---

## 9. RESUME HERE — tomorrow morning (check opportunities)

**Goal: see if any REAL opportunity exists (edge ≥2× AND meaningful money behind it).**

**Option A — quick count (1 min):** Railway → `web` → Deployments → Logs. Read `candidates now: N` and `+N newly logged`. Tells you *how many*, not the money behind them.

**Option B — full landscape (the good one, ~3 min):** on the Mac terminal:
```
cd ~/Downloads/bot
git pull
python3 scan_report.py
```
Read the `$@price` and `$<=20c` columns. **A real opportunity = a line with edge ≥2× AND meaningfully more than $20 of available money.** Today everything was $1–$3 = too thin. If it's still $1–$3, the answer stays "no tradeable edge, keep waiting."

**Decision rule for going real-money:** only if the paper screen shows lines that (a) clear all strict rules, (b) have real liquidity ≫ $20, and (c) actually start settling as WINS over many graded bets. None of that is true yet.

---

## 10. Open items / roadmap

- **🔒 SECURITY — revoke the exposed PAT.** The GitHub PAT `ghp_rtml…` was pasted into chat this session = treat as burned. GitHub → Settings → Developer settings → Personal access tokens → revoke it, generate a fresh one, store in Passwords/1Password. Update the stored value.
- **Calibrate goals-per-game per team** — default 1.4 is too high for minnows. (Widens, not closes, disagreements — only outcomes settle who's right.)
- **WebSocket feed** for sub-second reaction — needs the Kalshi API key (RSA-PSS signing); pairs with the live-trading phase.
- **Fixture-awareness v2** — let the model read who each team plays next (the deeper Jordan fix).
- **The big question:** any durable edge vs liquid Kalshi markets? Evidence so far says no. Screen keeps running.

---

## 11. If/when we go live with real money (NOT yet)

- Only after the paper screen shows a **positive, sustained** edge across many graded bets AND real liquidity exists to trade into.
- Requires: Kalshi API key + RSA-PSS request signing; `POST /trade-api/v2/portfolio/orders`; prefer **maker** (resting limit) orders; enforce the $100 bankroll cap + kill switch.
- Fees: `0.07 × contracts × price × (1−price)`, rounded up per order.

---

_End of handover. To resume: re-read §1, §6, §9, then run the §9 morning check._
