"""Exact card-drawing probabilities (the hypergeometric distribution).

Drawing n cards from a library of N that holds K lands, the chance of exactly k
lands is C(K, k) * C(N - K, n - k) / C(N, n), where C is "n choose k".
"""

from __future__ import annotations

from math import comb


def prob_exactly(k: int, successes: int, population: int, draws: int) -> float:
    """P(exactly k successes) when drawing `draws` cards without replacement."""
    if not 0 <= k <= draws or draws > population:
        return 0.0
    return comb(successes, k) * comb(population - successes, draws - k) / comb(population, draws)


def prob_at_least(k: int, successes: int, population: int, draws: int) -> float:
    """P(at least k successes) when drawing `draws` cards without replacement."""
    draws = min(draws, population)
    return sum(prob_exactly(i, successes, population, draws) for i in range(max(k, 0), draws + 1))


def cards_seen(turn: int, *, on_play: bool, hand_size: int = 7) -> int:
    """Cards seen by your turn `turn`: the opening hand plus one draw per turn,
    except that the player on the play skips their first draw."""
    return hand_size + turn - (1 if on_play else 0)
