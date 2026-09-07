"""Deterministic rating-deviation math for the canonical Dice rating system.

Persistence is intentionally handled by ``dice.rating_replay`` so the same
rating transitions can be tested, reported, and committed atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Iterable

from dice.elo import ESTABLISHED_K, PROVISIONAL_K, expected_score, k_factor, margin_multiplier, team_delta

INITIAL_RATING_DEVIATION = 350.0
MIN_RATING_DEVIATION = 50.0
MAX_RATING_DEVIATION = 350.0
INACTIVITY_PERIOD_DAYS = 30.0
INACTIVITY_GROWTH_PER_PERIOD = 50.0
POST_MATCH_RETENTION = 0.85
MIN_LEARNING_MULTIPLIER = 0.75
MAX_LEARNING_MULTIPLIER = 1.50


@dataclass(frozen=True, slots=True)
class RatingState:
    """Server-derived Elo and uncertainty state at one point in the replay."""

    elo: int = 1500
    deviation: float = INITIAL_RATING_DEVIATION
    ranked_games: int = 0
    last_ranked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RankedMatch:
    """Minimal ranked-game input needed for deterministic replay."""

    played_at: datetime
    team1: tuple[str, ...]
    team2: tuple[str, ...]
    winner_team: int
    team1_score: int
    team2_score: int
    game_id: str | None = None


@dataclass(frozen=True, slots=True)
class RatingTransition:
    """Before/after states for one ranked game in a replay."""

    game_id: str | None
    before: dict[str, RatingState]
    after: dict[str, RatingState]


def replay_ranked_history(
    matches: Iterable[RankedMatch],
    user_ids: Iterable[str],
) -> dict[str, RatingState]:
    """Replay ranked matches in time order using Elo plus bounded deviation.

    Keeping this function persistence-free makes historical corrections and
    rating snapshots deterministic and easy to test.
    """

    states, _ = replay_ranked_history_with_transitions(matches, user_ids)
    return states


def replay_ranked_history_with_transitions(
    matches: Iterable[RankedMatch],
    user_ids: Iterable[str],
) -> tuple[dict[str, RatingState], list[RatingTransition]]:
    """Replay history and retain per-game snapshots for persistence."""

    states = {user_id: RatingState() for user_id in user_ids}
    transitions: list[RatingTransition] = []
    ordered = sorted(enumerate(matches), key=lambda item: (item[1].played_at, item[0]))
    for _, match in ordered:
        if match.winner_team not in (1, 2):
            raise ValueError("winner_team must be 1 or 2")
        if not match.team1 or not match.team2 or len(match.team1) != len(match.team2):
            continue
        participants = (*match.team1, *match.team2)
        if any(user_id not in states for user_id in participants):
            raise ValueError("all ranked match players must have an initial state")
        if len(set(participants)) != len(participants):
            raise ValueError("ranked match players must be distinct")

        current: dict[str, RatingState] = {}
        for user_id in participants:
            prior = states[user_id]
            elapsed_days = (
                max(0.0, (match.played_at - prior.last_ranked_at).total_seconds() / 86400)
                if prior.last_ranked_at is not None
                else 0.0
            )
            current[user_id] = RatingState(
                elo=prior.elo,
                deviation=inflate_for_inactivity(prior.deviation, elapsed_days),
                ranked_games=prior.ranked_games,
                last_ranked_at=prior.last_ranked_at,
            )

        before = dict(current)
        team1_rating = sum(current[user_id].elo for user_id in match.team1) / len(match.team1)
        team2_rating = sum(current[user_id].elo for user_id in match.team2) / len(match.team2)
        team1_won = match.winner_team == 1
        winner_score = match.team1_score if team1_won else match.team2_score
        loser_score = match.team2_score if team1_won else match.team1_score
        margin_mult = margin_multiplier(winner_score, loser_score)
        for team, team_rating, opponent_rating, won in (
            (match.team1, team1_rating, team2_rating, team1_won),
            (match.team2, team2_rating, team1_rating, not team1_won),
        ):
            for user_id in team:
                prior = current[user_id]
                delta = bounded_team_delta(
                    team_rating,
                    opponent_rating,
                    won,
                    effective_k_factor(k_factor(prior.ranked_games), prior.deviation),
                    margin_mult,
                )
                states[user_id] = RatingState(
                    elo=prior.elo + delta,
                    deviation=after_ranked_game(prior.deviation),
                    ranked_games=prior.ranked_games + 1,
                    last_ranked_at=match.played_at,
                )
        transitions.append(
            RatingTransition(
                game_id=match.game_id,
                before=before,
                after={user_id: states[user_id] for user_id in participants},
            )
        )
    return states, transitions


def _bounded(value: float) -> float:
    return max(MIN_RATING_DEVIATION, min(MAX_RATING_DEVIATION, value))


def inflate_for_inactivity(deviation: float, days_since_last_game: float) -> float:
    """Increase uncertainty with elapsed time, never changing Elo itself."""

    if days_since_last_game <= 0:
        return _bounded(deviation)
    periods = days_since_last_game / INACTIVITY_PERIOD_DAYS
    return _bounded(deviation + INACTIVITY_GROWTH_PER_PERIOD * periods)


def after_ranked_game(deviation: float, days_since_last_game: float = 0) -> float:
    """Reduce uncertainty after one observed ranked result."""

    inflated = inflate_for_inactivity(deviation, days_since_last_game)
    return _bounded(inflated * POST_MATCH_RETENTION)


def learning_multiplier(deviation: float) -> float:
    """Map uncertainty to a bounded learning-rate multiplier."""

    normalized = (_bounded(deviation) - MIN_RATING_DEVIATION) / (
        MAX_RATING_DEVIATION - MIN_RATING_DEVIATION
    )
    return MIN_LEARNING_MULTIPLIER + normalized * (
        MAX_LEARNING_MULTIPLIER - MIN_LEARNING_MULTIPLIER
    )


def effective_k_factor(base_k: int, deviation: float) -> int:
    """Return a confidence-adjusted K-factor without double-counting placement.

    The provisional K already makes placement twice as responsive as
    established play. Normalize its deviation multiplier so a new player's
    first game starts at that existing K rather than stacking to 1.5x it.
    As placement evidence arrives, the same deviation curve tapers the K.
    Established ratings use the full multiplier so inactivity can make them
    more responsive again.
    """

    if base_k not in {PROVISIONAL_K, ESTABLISHED_K}:
        raise ValueError("base_k must be the Dice provisional or established K-factor")
    multiplier = learning_multiplier(deviation)
    if base_k == PROVISIONAL_K:
        multiplier /= MAX_LEARNING_MULTIPLIER
    return round(base_k * multiplier)


def bounded_team_delta(
    team_rating: float,
    opponent_rating: float,
    won: bool,
    k: int,
    margin_mult: float = 1.0,
) -> int:
    """Apply the existing Elo result while limiting one game to one K.

    Expected score and margin still determine movement inside the bound. The
    ceiling prevents a dominant upset from stacking those factors into a
    socially disruptive multi-K jump. Because the bound scales with each
    player's effective K, it preserves the confidence-based relationship
    between players instead of introducing a flat rating-point constant.
    """

    delta = team_delta(team_rating, opponent_rating, won, k, margin_mult)
    return max(-k, min(k, delta))


def team_deviation(player_deviations: tuple[float, ...]) -> float:
    """Combine player uncertainty using a deterministic RMS average."""

    if not player_deviations:
        raise ValueError("a team needs at least one rating deviation")
    return sqrt(sum(_bounded(value) ** 2 for value in player_deviations) / len(player_deviations))


def probability(team_rating: float, opponent_rating: float) -> float:
    """Keep Elo's calibrated win-probability mapping unchanged."""

    return expected_score(team_rating, opponent_rating)
