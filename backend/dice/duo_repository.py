"""Read-only repository boundary for the derived Dice duo ladder."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from supabase import Client

from dice.duo_rating import (
    DuoMatch,
    DuoRatingState,
    DuoTransition,
    rank_duos,
    replay_duo_history_with_transitions,
)
from dice.schemas import (
    DuoDetailOut,
    DuoHeadToHead,
    DuoLadderOut,
    DuoMember,
    DuoSummary,
    DuoTransitionOut,
)

MAX_DUO_REPLAY_GAMES = 5000


def _source(supabase: Client) -> tuple[list[dict], list[DuoMatch]]:
    """Read one atomic, complete analytics snapshot before replaying.

    The RPC is a stable MVCC view and is intentionally reused from individual
    rating progress instead of issuing uncapped PostgREST table reads.
    """
    snapshot = supabase.rpc(
        "dice_duo_replay_snapshot", {"p_max_games": MAX_DUO_REPLAY_GAMES}
    ).execute().data or {}
    if snapshot.get("snapshot_version") != "dice-rating-analytics/v1":
        raise RuntimeError("unsupported rating analytics snapshot")
    if snapshot.get("error") == "history_limit_exceeded":
        raise RuntimeError("duo replay history exceeds the configured limit")
    profiles = snapshot.get("profiles") or []
    games = snapshot.get("games") or []
    players = snapshot.get("players") or []
    players_by_game: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for player in players:
        players_by_game[player["game_id"]][player["team"]].append(player["user_id"])
    matches = [
        DuoMatch(
            game_id=game["id"],
            played_at=game["played_at"],
            created_at=game.get("created_at"),
            team1=tuple(players_by_game[game["id"]][1]),
            team2=tuple(players_by_game[game["id"]][2]),
            winner_team=game.get("winner_team"),
            team1_score=game["team1_score"],
            team2_score=game["team2_score"],
            ranked=game.get("ranked", False),
            live_result_state=game.get("live_result_state"),
        )
        for game in games
    ]
    return profiles, matches


def _summary(
    state: DuoRatingState,
    profiles: dict[str, dict],
    rank: int | None = None,
    game_ids: list[str] | None = None,
) -> DuoSummary:
    members = tuple(
        DuoMember(
            user_id=user_id,
            display_name=profiles.get(user_id, {}).get("display_name", "Unknown"),
            avatar_url=profiles.get(user_id, {}).get("avatar_url"),
        )
        for user_id in state.members
    )
    return DuoSummary(
        duo_id=state.duo_id,
        members=members,  # type: ignore[arg-type]
        elo=state.elo,
        rating_deviation=round(state.deviation, 2),
        conservative_score=round(state.conservative_score, 2),
        wins=state.wins,
        losses=state.losses,
        games=state.ranked_games,
        win_rate=round(state.win_rate, 4),
        placed=state.placed,
        homepage_eligible=state.homepage_eligible,
        rank=rank,
        current_streak=state.current_streak,
        best_streak=state.best_streak,
        game_ids=game_ids or [],
    )


def _transition_out(transition: DuoTransition) -> DuoTransitionOut:
    return DuoTransitionOut(
        game_id=transition.game_id,
        opponent_duo_id=transition.opponent_duo_id,
        before_elo=transition.before_elo,
        after_elo=transition.after_elo,
        delta=transition.delta,
        result=transition.result,
        score=transition.score,
        played_at=transition.played_at,
    )


def _replay(supabase: Client):
    profiles, matches = _source(supabase)
    # Leaderboard-hidden profiles are omitted from the replay itself, not only
    # from its output.  Otherwise a visible duo's rating could be influenced by
    # an undisclosed opponent while its evidence/counts correctly hide that
    # game, producing an internally inconsistent public result.
    visible_ids = {
        row["user_id"] for row in profiles if not row.get("hide_from_leaderboard", False)
    }
    public_matches = [
        match
        for match in matches
        if all(member in visible_ids for member in (*match.team1, *match.team2))
    ]
    states, transitions = replay_duo_history_with_transitions(public_matches)
    ladder = rank_duos(states)
    return profiles, ladder, states, transitions


def _visible_states(states: dict[str, DuoRatingState], profiles: list[dict]) -> dict[str, DuoRatingState]:
    visible_ids = {row["user_id"] for row in profiles if not row.get("hide_from_leaderboard", False)}
    return {
        duo_id: state
        for duo_id, state in states.items()
        if all(member in visible_ids for member in state.members)
    }


def _competition_ranks(states: list[DuoRatingState]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    previous_elo: int | None = None
    for position, state in enumerate(states, 1):
        if previous_elo is None or state.elo != previous_elo:
            rank = position
        ranks[state.duo_id] = rank
        previous_elo = state.elo
    return ranks


def list_duo_ladder(
    supabase: Client, limit: int = 100, homepage_eligible_only: bool = False
) -> DuoLadderOut:
    profiles, ladder, _, transitions = _replay(supabase)
    visible = _visible_states({state.duo_id: state for state in (*ladder.ranked, *ladder.to_watch)}, profiles)
    profile_map = {row["user_id"]: row for row in profiles}
    game_ids_by_duo: dict[str, list[str]] = defaultdict(list)
    for transition in transitions:
        game_ids_by_duo[transition.duo_id].append(transition.game_id)
    ranked_states = [state for state in ladder.ranked if state.duo_id in visible]
    if homepage_eligible_only:
        ranked_states = [state for state in ranked_states if state.homepage_eligible]
    ranked_states = ranked_states[:limit]
    ranks = _competition_ranks([state for state in ladder.ranked if state.duo_id in visible])
    ranked = [_summary(state, profile_map, ranks[state.duo_id], game_ids_by_duo.get(state.duo_id)) for state in ranked_states]
    to_watch = [
        _summary(state, profile_map, game_ids=game_ids_by_duo.get(state.duo_id))
        for state in ladder.to_watch
        if state.duo_id in visible
    ]
    to_watch = to_watch[:limit]
    return DuoLadderOut(ranked=ranked, to_watch=to_watch)


def get_duo_detail(supabase: Client, duo_id: str) -> DuoDetailOut | None:
    profiles, _, states, transitions = _replay(supabase)
    state = states.get(duo_id)
    visible = _visible_states(states, profiles)
    if state is None or duo_id not in visible:
        return None
    profile_map = {row["user_id"]: row for row in profiles}
    public_states = {candidate.duo_id: candidate for candidate in states.values() if candidate.duo_id in visible}
    placed = sorted(
        (candidate for candidate in public_states.values() if candidate.placed),
        key=lambda candidate: (-candidate.conservative_score, -candidate.elo, candidate.duo_id),
    )
    ranks = _competition_ranks(placed)
    rank = ranks.get(duo_id)
    own = [transition for transition in transitions if transition.duo_id == duo_id]
    public_own = [transition for transition in own if transition.opponent_duo_id in public_states]
    public_wins = sum(transition.result == "win" for transition in public_own)
    public_losses = len(public_own) - public_wins
    public_current = 0
    public_best = 0
    for transition in public_own:
        public_current = public_current + 1 if transition.result == "win" else 0
        public_best = max(public_best, public_current)
    public_state = replace(
        state,
        ranked_games=len(public_own),
        wins=public_wins,
        losses=public_losses,
        current_streak=public_current,
        best_streak=public_best,
    )
    summary = _summary(public_state, profile_map, rank, [transition.game_id for transition in public_own])
    grouped: dict[str, list[DuoTransition]] = defaultdict(list)
    for transition in public_own:
        grouped[transition.opponent_duo_id].append(transition)
    head_to_head = [
        DuoHeadToHead(
            opponent_duo_id=opponent_id,
            opponent_members=tuple(
                DuoMember(
                    user_id=user_id,
                    display_name=profile_map.get(user_id, {}).get("display_name", "Unknown"),
                    avatar_url=profile_map.get(user_id, {}).get("avatar_url"),
                )
                for user_id in public_states[opponent_id].members
            ),  # type: ignore[arg-type]
            wins=sum(transition.result == "win" for transition in opponent_transitions),
            losses=sum(transition.result == "loss" for transition in opponent_transitions),
            games=len(opponent_transitions),
            latest_meeting=max(transition.played_at for transition in opponent_transitions),
            game_ids=[transition.game_id for transition in opponent_transitions],
        )
        for opponent_id, opponent_transitions in sorted(grouped.items())
    ]
    evidence = [_transition_out(transition) for transition in public_own]
    return DuoDetailOut(summary=summary, rating_history=evidence, games=evidence, head_to_head=head_to_head)


__all__ = ["get_duo_detail", "list_duo_ladder"]
