"""Point-in-time feature rows for Dice prediction models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from collections import defaultdict
from math import log1p

from dice.elo import STARTING_ELO, expected_score, k_factor, margin_multiplier, team_delta
from dice.rating_deviation import RankedMatch

DATASET_VERSION = "dice-prediction-dataset/v1"
DEFAULT_TARGET_SCORE = 11


def ranked_matches_from_rows(games: list[dict], players: list[dict]) -> list[RankedMatch]:
    """Adapt official persistence rows to ordered, eligible model inputs."""

    players_by_game: dict[str, list[dict]] = defaultdict(list)
    for row in players:
        players_by_game[row["game_id"]].append(row)
    matches: list[RankedMatch] = []
    ordered = sorted(games, key=lambda row: (row["played_at"], row["created_at"], row["id"]))
    for game in ordered:
        if game.get("live_result_state") not in (None, "official"):
            continue
        roster = players_by_game[game["id"]]
        team1 = tuple(row["user_id"] for row in roster if row["team"] == 1)
        team2 = tuple(row["user_id"] for row in roster if row["team"] == 2)
        if not game["ranked"] or game["winner_team"] is None:
            continue
        if not team1 and not team2:
            raise ValueError(f"completed ranked game {game['id']} has no roster")
        if len(team1) == len(team2) and len(team1) != 2:
            # Valid historical singles/other formats are outside the live 2v2
            # serving cohort and must not influence its promotion metrics.
            continue
        if len(team1) != 2 or len(team2) != 2:
            raise ValueError(f"completed ranked game {game['id']} is not a complete 2v2 roster")
        played_at = datetime.fromisoformat(game["played_at"].replace("Z", "+00:00"))
        matches.append(RankedMatch(played_at=played_at, team1=team1, team2=team2,
                                   winner_team=game["winner_team"], team1_score=game["team1_score"],
                                   team2_score=game["team2_score"], game_id=game["id"]))
    return matches


@dataclass(frozen=True, slots=True)
class PredictionRow:
    dataset_version: str
    game_id: str
    played_at: str
    team1: tuple[str, ...]
    team2: tuple[str, ...]
    team_size: int
    target_score: int
    team1_prior_win_rate: float
    team2_prior_win_rate: float
    prior_win_rate_difference: float
    team1_prior_games: float
    team2_prior_games: float
    prior_experience_difference: float
    team1_days_since_last: float | None
    team2_days_since_last: float | None
    prior_recency_difference: float
    elo_probability: float
    team1_won: int

    def as_dict(self) -> dict:
        return asdict(self)


def build_prediction_dataset(matches: list[RankedMatch]) -> list[PredictionRow]:
    """Build reproducible rows using only information available pregame."""

    ordered = sorted(enumerate(matches), key=lambda item: (item[1].played_at, item[0]))
    games: dict[str, int] = {}
    wins: dict[str, int] = {}
    ratings: dict[str, int] = {}
    last_played: dict[str, datetime] = {}
    rows: list[PredictionRow] = []
    seen_game_ids: set[str] = set()
    for index, match in ordered:
        game_id = match.game_id or f"ordered-{index}"
        if game_id in seen_game_ids:
            raise ValueError("prediction game IDs must be unique")
        seen_game_ids.add(game_id)
        participants = (*match.team1, *match.team2)
        if len(set(participants)) != len(participants):
            raise ValueError("prediction roster players must be distinct")
        if match.winner_team not in (1, 2) or len(match.team1) != 2 or len(match.team2) != 2:
            raise ValueError("prediction rows require a completed 2v2 match")
        played_at = match.played_at if match.played_at.tzinfo else match.played_at.replace(tzinfo=timezone.utc)

        def team_average(team: tuple[str, ...], values: dict[str, int], default: int = 0) -> float:
            return sum(values.get(user_id, default) for user_id in team) / len(team)

        def prior_rate(team: tuple[str, ...]) -> float:
            return sum((wins.get(user_id, 0) + 1) / (games.get(user_id, 0) + 2) for user_id in team) / len(team)

        def days_since(team: tuple[str, ...]) -> float | None:
            values = [(played_at - last_played[user_id]).total_seconds() / 86400
                      for user_id in team if user_id in last_played]
            return sum(values) / len(values) if values else None

        rate1, rate2 = prior_rate(match.team1), prior_rate(match.team2)
        games1, games2 = team_average(match.team1, games), team_average(match.team2, games)
        days1, days2 = days_since(match.team1), days_since(match.team2)
        rating1 = team_average(match.team1, ratings, STARTING_ELO)
        rating2 = team_average(match.team2, ratings, STARTING_ELO)
        rows.append(PredictionRow(
            dataset_version=DATASET_VERSION, game_id=game_id, played_at=played_at.isoformat(),
            team1=match.team1, team2=match.team2, team_size=len(match.team1),
            # Historical manual games predate saved rules. Dice's pregame
            # target is 11; deriving this from the final score would leak.
            target_score=DEFAULT_TARGET_SCORE,
            team1_prior_win_rate=rate1, team2_prior_win_rate=rate2,
            prior_win_rate_difference=rate1 - rate2,
            team1_prior_games=games1, team2_prior_games=games2,
            prior_experience_difference=log1p(games1) - log1p(games2),
            team1_days_since_last=days1, team2_days_since_last=days2,
            prior_recency_difference=((days2 or 0) - (days1 or 0)) / 30,
            elo_probability=expected_score(rating1, rating2), team1_won=int(match.winner_team == 1),
        ))

        team1_won = match.winner_team == 1
        margin = margin_multiplier(match.team1_score if team1_won else match.team2_score,
                                   match.team2_score if team1_won else match.team1_score)
        for team, team_rating, opponent_rating, won in (
            (match.team1, rating1, rating2, team1_won),
            (match.team2, rating2, rating1, not team1_won),
        ):
            for user_id in team:
                prior_games = games.get(user_id, 0)
                ratings[user_id] = ratings.get(user_id, STARTING_ELO) + team_delta(
                    team_rating, opponent_rating, won, k_factor(prior_games), margin
                )
                games[user_id] = prior_games + 1
                wins[user_id] = wins.get(user_id, 0) + int(won)
                last_played[user_id] = played_at
    return rows
