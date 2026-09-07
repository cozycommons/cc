"""Team ELO rating math for Dice.

Ratings are tracked per player but updated at the team level: a team's
effective rating is the average of its players' ratings (2v2 teams have two
players each; 1v1 "teams" are just the one player), and teammates receive
the same rating delta for a given game. This is the standard simplification
used by most casual team-ELO trackers that don't implement a full
multi-player system like TrueSkill.

Only ranked games affect ratings. Because editing or deleting a past ranked
game changes the sequence every later game was computed from, ratings are
never trusted as incrementally-correct — they're recomputed by replaying
every ranked game in chronological order from a clean 1500 whenever a ranked
game is created, edited, or deleted.
"""

from __future__ import annotations

STARTING_ELO = 1500

# K-factor tapers down once a player has an established rating, the same
# provisional/established split used by USCF/FIDE chess ratings — new
# players' ratings move fast until they've played enough ranked games to
# mean something, then stabilize.
PROVISIONAL_K = 40
ESTABLISHED_K = 20
PROVISIONAL_GAMES_THRESHOLD = 3


def k_factor(ranked_games_played_before_this_game: int) -> int:
    if ranked_games_played_before_this_game < PROVISIONAL_GAMES_THRESHOLD:
        return PROVISIONAL_K
    return ESTABLISHED_K


def expected_score(team_rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_rating - team_rating) / 400.0))


# Games are played to a target score that varies game-to-game (e.g. some
# nights are played to 7, others to 21), so there's no fixed "point margin"
# to compare across games. Instead we treat the winner's score as that
# game's target and look at how close the loser got to it: a razor-close
# finish (e.g. 21-20) barely moves ratings beyond the base win/loss result,
# while a shutout (21-0) moves them up to 2x as much.
MIN_MARGIN_MULTIPLIER = 1.0
MAX_MARGIN_MULTIPLIER = 2.0


def margin_multiplier(winner_score: int, loser_score: int) -> float:
    if winner_score <= 0:
        return MIN_MARGIN_MULTIPLIER
    ratio = max(0.0, min(1.0, loser_score / winner_score))
    dominance = 1.0 - ratio
    return MIN_MARGIN_MULTIPLIER + dominance * (MAX_MARGIN_MULTIPLIER - MIN_MARGIN_MULTIPLIER)


def team_delta(
    team_rating: float, opponent_rating: float, won: bool, k: int, margin_mult: float = 1.0
) -> int:
    actual = 1.0 if won else 0.0
    expected = expected_score(team_rating, opponent_rating)
    return round(k * margin_mult * (actual - expected))
