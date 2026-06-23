"""
model.py  —  the "brain" (now mid-tournament aware).

P(team scores >= N total goals) =
    P( goals_already_banked + goals_in_remaining_games  >=  N )

Mid-tournament that means: subtract goals already scored, and only roll the
dice over the games the team still has left (driven by how far they advance).

Pure math, no API, no key. Safe to run anywhere.
"""

import math

# Stage of elimination -> total games the team plays across the whole tournament.
# 2026 format; semifinal losers also play the 3rd-place match, so SF/Final/Winner = 8.
STAGE_GAMES = {
    "group": 3, "r32": 4, "r16": 5, "qf": 6, "sf": 8, "final": 8, "winner": 8,
}


def normalize(stage_probs):
    """Rescale Kalshi's stage prices (which carry vig) so they sum to 1."""
    s = sum(stage_probs.values())
    return {k: v / s for k, v in stage_probs.items()} if s else stage_probs


def poisson_sf(n, lam):
    """P(X >= n) for X ~ Poisson(lam). Iterative; no giant factorials."""
    if n <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    term = math.exp(-lam)          # k = 0
    cdf = term
    for k in range(1, n):
        term *= lam / k
        cdf += term
    return max(0.0, 1.0 - cdf)


def p_goals_at_least(n, stage_probs, goals_per_game, banked=0, games_played=0):
    """Our independent estimate of P(team finishes with >= n goals)."""
    need = n - banked                       # goals still required
    if need <= 0:
        return 1.0                          # already cleared this line
    sp = normalize(stage_probs)
    total = 0.0
    for stage, p in sp.items():
        remaining = max(0, STAGE_GAMES[stage] - games_played)
        lam = remaining * goals_per_game    # expected goals over games left
        total += p * poisson_sf(need, lam)
    return total


def evaluate_line(threshold, no_ask_cents, stage_probs, gpg,
                  banked=0, games_played=0, edge_mult=2.0, max_price=20):
    """Decide whether to buy NO on the 'threshold+ goals' market."""
    model_no = 1.0 - p_goals_at_least(threshold, stage_probs, gpg,
                                      banked=banked, games_played=games_played)
    price = no_ask_cents / 100.0
    buy = (no_ask_cents <= max_price) and (model_no >= edge_mult * price)
    return {
        "threshold":  threshold,
        "no_ask_c":   no_ask_cents,
        "model_no_%": round(model_no * 100, 1),
        "price_%":    round(price * 100, 1),
        "need_2x_%":  round(edge_mult * price * 100, 1),
        "BUY":        "YES" if buy else "-",
    }
