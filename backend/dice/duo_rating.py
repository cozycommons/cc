"""Pure, deterministic replay for Dice's exact two-player duo ladder.

The module deliberately has no persistence or web-framework dependency.  A
caller supplies canonical match history and receives the same duo states and
game-linked transitions every time, including after a historical correction.
Individual-player ratings are not read or written here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from dice.elo import (
    PROVISIONAL_GAMES_THRESHOLD,
    STARTING_ELO,
    k_factor,
    margin_multiplier,
)
from dice.rating_deviation import (
    INITIAL_RATING_DEVIATION,
    after_ranked_game,
    bounded_team_delta,
    effective_k_factor,
    inflate_for_inactivity,
)

DUO_PLACEMENT_GAMES = PROVISIONAL_GAMES_THRESHOLD
DUO_HOMEPAGE_GAMES = DUO_PLACEMENT_GAMES


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def canonical_duo_members(first: str, second: str) -> tuple[str, str]:
    """Return the exact unordered pair in its stable identity order."""

    if not isinstance(first, str) or not isinstance(second, str) or not first or not second:
        raise ValueError("duo members must be non-empty strings")
    if first == second:
        raise ValueError("a duo requires two distinct players")
    return tuple(sorted((first, second)))


def canonical_duo_id(first: str, second: str) -> str:
    """Build a readable, collision-free ID from the sorted member IDs."""

    left, right = canonical_duo_members(first, second)
    # UUID user IDs do not contain this separator; length-prefixing keeps the
    # function safe for arbitrary IDs as well.
    return f"{len(left)}:{left}{len(right)}:{right}"


def _members_from_duo_id(duo_id: str) -> tuple[str, str]:
    """Decode the module's length-prefixed canonical ID for seeded replay."""

    try:
        first_length_end = duo_id.index(":")
        first_length = int(duo_id[:first_length_end])
        first_start = first_length_end + 1
        second_length_start = first_start + first_length
        second_length_end = duo_id.index(":", second_length_start)
        second_length = int(duo_id[second_length_start:second_length_end])
        second_start = second_length_end + 1
        members = (
            duo_id[first_start:second_length_start],
            duo_id[second_start:second_start + second_length],
        )
    except (ValueError, IndexError):
        raise ValueError("duo_ids must use canonical duo IDs") from None
    if (
        len(members[0]) != first_length
        or len(members[1]) != second_length
        or second_start + second_length != len(duo_id)
    ):
        raise ValueError("duo_ids must use canonical duo IDs")
    return canonical_duo_members(*members)


@dataclass(frozen=True, slots=True)
class DuoMatch:
    """The replay-ready portion of a completed Dice game."""

    game_id: str
    played_at: datetime
    team1: tuple[str, ...]
    team2: tuple[str, ...]
    winner_team: int | None
    team1_score: int
    team2_score: int
    ranked: bool = True
    completed: bool = True
    live_result_state: str | None = "official"
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DuoRatingState:
    duo_id: str
    members: tuple[str, str]
    elo: int = STARTING_ELO
    deviation: float = INITIAL_RATING_DEVIATION
    ranked_games: int = 0
    wins: int = 0
    losses: int = 0
    last_ranked_at: datetime | None = None
    current_streak: int = 0
    best_streak: int = 0

    @property
    def games(self) -> int:
        return self.ranked_games

    @property
    def games_played(self) -> int:
        return self.ranked_games

    @property
    def elo_rating(self) -> int:
        return self.elo

    @property
    def rating_deviation(self) -> float:
        return self.deviation

    @property
    def win_rate(self) -> float:
        return self.wins / self.ranked_games if self.ranked_games else 0.0

    @property
    def placed(self) -> bool:
        return self.ranked_games >= DUO_PLACEMENT_GAMES

    @property
    def homepage_eligible(self) -> bool:
        return self.ranked_games >= DUO_HOMEPAGE_GAMES

    @property
    def conservative_score(self) -> float:
        return conservative_duo_score(self)


@dataclass(frozen=True, slots=True)
class DuoTransition:
    """One evidence-bearing rating transition for one side of a game."""

    game_id: str
    duo_id: str
    opponent_duo_id: str
    before_elo: int
    after_elo: int
    delta: int
    before_deviation: float
    after_deviation: float
    result: str
    score: tuple[int, int]
    played_at: datetime
    before: DuoRatingState
    after: DuoRatingState


@dataclass(frozen=True, slots=True)
class DuoLadder:
    ranked: tuple[DuoRatingState, ...]
    to_watch: tuple[DuoRatingState, ...]


def _coerce_match(match: DuoMatch | Mapping[str, object]) -> DuoMatch:
    if isinstance(match, DuoMatch):
        return match
    if not isinstance(match, Mapping):
        raise TypeError("duo matches must be DuoMatch values or mappings")
    raw_team1 = match.get("team1", ())
    raw_team2 = match.get("team2", ())
    return DuoMatch(
        game_id=str(match["game_id"] if "game_id" in match else match["id"]),
        played_at=match.get("played_at") or match.get("completed_at"),  # type: ignore[arg-type]
        team1=tuple(raw_team1) if isinstance(raw_team1, (tuple, list)) else (),
        team2=tuple(raw_team2) if isinstance(raw_team2, (tuple, list)) else (),
        winner_team=match.get("winner_team"),  # type: ignore[arg-type]
        # Preserve malformed values for `_eligible` to reject instead of
        # coercing a corrupt source row into a valid score.
        team1_score=match.get("team1_score", 0),  # type: ignore[arg-type]
        team2_score=match.get("team2_score", 0),  # type: ignore[arg-type]
        ranked=bool(match.get("ranked", True)),
        completed=bool(
            match.get("completed", match.get("status") in (None, "completed", "official"))
        ),
        live_result_state=match.get("live_result_state", "official"),  # type: ignore[arg-type]
        created_at=match.get("created_at"),  # type: ignore[arg-type]
    )


def _eligible(match: DuoMatch) -> tuple[tuple[str, str], tuple[str, str]] | None:
    if not match.ranked or not match.completed or match.winner_team not in (1, 2):
        return None
    if match.live_result_state not in (None, "official", "completed"):
        return None
    if not isinstance(match.team1, (tuple, list)) or not isinstance(
        match.team2, (tuple, list)
    ):
        return None
    if len(match.team1) != 2 or len(match.team2) != 2:
        return None
    if (
        not isinstance(match.team1_score, int)
        or not isinstance(match.team2_score, int)
        or match.team1_score < 0
        or match.team2_score < 0
        or (match.winner_team == 1 and match.team1_score <= match.team2_score)
        or (match.winner_team == 2 and match.team2_score <= match.team1_score)
    ):
        return None
    participants = (*match.team1, *match.team2)
    if any(not isinstance(user_id, str) or not user_id for user_id in participants):
        return None
    if len(set(participants)) != 4:
        return None
    try:
        return canonical_duo_members(*match.team1), canonical_duo_members(*match.team2)
    except ValueError:
        return None


def eligible_duo_matches(
    matches: Iterable[DuoMatch | Mapping[str, object]],
) -> list[tuple[DuoMatch, tuple[str, str], tuple[str, str]]]:
    """Filter and stably order completed ranked 2v2 games."""

    eligible: list[tuple[DuoMatch, tuple[str, str], tuple[str, str]]] = []
    seen_game_ids: set[str] = set()
    for raw in matches:
        match = _coerce_match(raw)
        if not match.game_id or match.game_id in seen_game_ids:
            if match.game_id in seen_game_ids:
                raise ValueError("duo match game IDs must be unique")
            continue
        seen_game_ids.add(match.game_id)
        pair = _eligible(match)
        if pair is not None:
            eligible.append((match, *pair))
    return sorted(
        eligible,
        key=lambda item: (
            _as_utc(item[0].played_at),
            _as_utc(item[0].created_at or item[0].played_at),
            item[0].game_id,
        ),
    )


def conservative_duo_score(
    state: DuoRatingState, uncertainty_penalty: float = 1.0
) -> float:
    """Rank by lower-confidence-bound strength, never by raw win rate."""

    if uncertainty_penalty < 0:
        raise ValueError("uncertainty_penalty must be non-negative")
    return state.elo - uncertainty_penalty * state.deviation


def conservative_score(state: DuoRatingState, uncertainty_penalty: float = 1.0) -> float:
    """Short alias for callers rendering the ladder's primary sort metric."""

    return conservative_duo_score(state, uncertainty_penalty)


def _initial_state(members: tuple[str, str]) -> DuoRatingState:
    return DuoRatingState(canonical_duo_id(*members), members)


def replay_duo_history_with_transitions(
    matches: Iterable[DuoMatch | Mapping[str, object]],
    duo_ids: Iterable[str] = (),
) -> tuple[dict[str, DuoRatingState], list[DuoTransition]]:
    """Replay eligible history chronologically from clean duo states."""

    states: dict[str, DuoRatingState] = {}
    for duo_id in duo_ids:
        if not isinstance(duo_id, str) or not duo_id:
            raise ValueError("duo_ids must contain non-empty strings")
        states.setdefault(duo_id, DuoRatingState(duo_id, _members_from_duo_id(duo_id)))
    transitions: list[DuoTransition] = []
    for match, team1, team2 in eligible_duo_matches(matches):
        duo_pairs = (team1, team2)
        duo_keys = tuple(canonical_duo_id(*members) for members in duo_pairs)
        for duo_id, members in zip(duo_keys, duo_pairs):
            if duo_id not in states or states[duo_id].members == ("", ""):
                states[duo_id] = _initial_state(members)
        before_states: list[DuoRatingState] = []
        for duo_id in duo_keys:
            prior = states[duo_id]
            elapsed_days = (
                max(
                    0.0,
                    (_as_utc(match.played_at) - _as_utc(prior.last_ranked_at)).total_seconds()
                    / 86400,
                )
                if prior.last_ranked_at is not None
                else 0.0
            )
            before_states.append(
                DuoRatingState(
                    duo_id=prior.duo_id,
                    members=prior.members,
                    elo=prior.elo,
                    deviation=inflate_for_inactivity(prior.deviation, elapsed_days),
                    ranked_games=prior.ranked_games,
                    wins=prior.wins,
                    losses=prior.losses,
                    last_ranked_at=prior.last_ranked_at,
                    current_streak=prior.current_streak,
                    best_streak=prior.best_streak,
                )
            )
        team1_won = match.winner_team == 1
        margin = margin_multiplier(
            match.team1_score if team1_won else match.team2_score,
            match.team2_score if team1_won else match.team1_score,
        )
        for index, (duo_id, prior) in enumerate(zip(duo_keys, before_states)):
            opponent = before_states[1 - index]
            won = team1_won if index == 0 else not team1_won
            k = effective_k_factor(k_factor(prior.ranked_games), prior.deviation)
            delta = bounded_team_delta(prior.elo, opponent.elo, won, k, margin)
            streak = prior.current_streak + 1 if won else 0
            after = DuoRatingState(
                duo_id=prior.duo_id,
                members=prior.members,
                elo=prior.elo + delta,
                deviation=after_ranked_game(prior.deviation),
                ranked_games=prior.ranked_games + 1,
                wins=prior.wins + int(won),
                losses=prior.losses + int(not won),
                last_ranked_at=_as_utc(match.played_at),
                current_streak=streak,
                best_streak=max(prior.best_streak, streak),
            )
            states[duo_id] = after
            transitions.append(
                DuoTransition(
                    game_id=match.game_id,
                    duo_id=duo_id,
                    opponent_duo_id=opponent.duo_id,
                    before_elo=prior.elo,
                    after_elo=after.elo,
                    delta=delta,
                    before_deviation=prior.deviation,
                    after_deviation=after.deviation,
                    result="win" if won else "loss",
                    score=(
                        (match.team1_score, match.team2_score)
                        if index == 0
                        else (match.team2_score, match.team1_score)
                    ),
                    played_at=_as_utc(match.played_at),
                    before=prior,
                    after=after,
                )
            )
    return states, transitions


def replay_duo_history(
    matches: Iterable[DuoMatch | Mapping[str, object]],
    duo_ids: Iterable[str] = (),
) -> dict[str, DuoRatingState]:
    return replay_duo_history_with_transitions(matches, duo_ids)[0]


def rank_duos(states: Mapping[str, DuoRatingState] | Iterable[DuoRatingState]) -> DuoLadder:
    """Split placed and provisional states and sort by the displayed Elo."""

    values = tuple(states.values()) if isinstance(states, Mapping) else tuple(states)
    ranked = sorted(
        (state for state in values if state.placed),
        key=lambda state: (-state.elo, state.duo_id),
    )
    to_watch = sorted(
        (state for state in values if 0 < state.ranked_games < DUO_PLACEMENT_GAMES),
        key=lambda state: (-state.elo, state.duo_id),
    )
    return DuoLadder(tuple(ranked), tuple(to_watch))


def build_duo_ladder(
    matches: Iterable[DuoMatch | Mapping[str, object]],
) -> DuoLadder:
    states = replay_duo_history(matches)
    return rank_duos(states)


__all__ = [
    "DUO_HOMEPAGE_GAMES",
    "DUO_PLACEMENT_GAMES",
    "DuoLadder",
    "DuoMatch",
    "DuoRatingState",
    "DuoTransition",
    "build_duo_ladder",
    "canonical_duo_id",
    "canonical_duo_members",
    "conservative_score",
    "conservative_duo_score",
    "eligible_duo_matches",
    "replay_duo_history",
    "replay_duo_history_with_transitions",
    "rank_duos",
]
