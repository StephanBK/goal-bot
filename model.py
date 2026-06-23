"""
model.py  —  Phase 3 step 1: the "brain".

Turns Kalshi's stage-of-elimination probabilities into an INDEPENDENT estimate
of P(team scores fewer than N goals all tournament), then checks it against the
NO price using your rule: buy only if true_NO >= 2x price AND price <= 20c.

Why this isn't circular: stage-of-elimination and the goals ladder are SEPARATE
Kalshi markets. We use one to value the other and trade the disagreement.

No external data, no API key. Pure math — safe to run anywhere.
"""

import math

# --- Stage of elimination -> number of games the team plays --------------
# 2026 format: 3 group games, then R32, R16, QF, SF, Final.
# A semifinal loser ALSO plays the 3rd-place match, so SF/Final/Winner = 8 games.
STAGE_GAMES = {
    "group":  3,
    "r32":    4,
    "r16":    5,
    "qf":     6,
    "sf":     8,
    "final":  8,   # runner-up
    "winner": 8,
}


def normalize(stage_probs):
    """Kalshi prices carry a little 'vig' and won't sum to exactly 1.
    We rescale so the distribution is clean (sums to 1)."""
    s = sum(stage_probs.values())
    return {k: v / s for k, v in stage_probs.items()}


def poisson_sf(n, lam):
    """P(X >= n) for X ~ Poisson(lam). Models total goals over the games played.
    Iterative so it never builds huge factorials."""
    if n <= 0:
        return 1.0
    term = math.exp(-lam)      # k = 0 term
    cdf = term
    for k in range(1, n):
        term *= lam / k        # next term from previous
        cdf += term
    return max(0.0, 1.0 - cdf)


def p_goals_at_least(n, stage_probs, goals_per_game):
    """Our model: marginalize P(goals >= n) over how far the team advances."""
    sp = normalize(stage_probs)
    total = 0.0
    for stage, p in sp.items():
        lam = STAGE_GAMES[stage] * goals_per_game
        total += p * poisson_sf(n, lam)
    return total


def evaluate_line(threshold, no_ask_cents, stage_probs, gpg,
                  edge_mult=2.0, max_price=20):
    """Decide whether to buy NO on the 'threshold+ goals' market."""
    model_no = 1.0 - p_goals_at_least(threshold, stage_probs, gpg)  # P(goals < N)
    price = no_ask_cents / 100.0
    buy = (no_ask_cents <= max_price) and (model_no >= edge_mult * price)
    return {
        "threshold":   threshold,
        "no_ask_c":    no_ask_cents,
        "model_no_%":  round(model_no * 100, 1),   # our true NO probability
        "price_%":     round(price * 100, 1),      # market's NO probability
        "need_2x_%":   round(edge_mult * price * 100, 1),
        "BUY":         "YES" if buy else "-",
    }
