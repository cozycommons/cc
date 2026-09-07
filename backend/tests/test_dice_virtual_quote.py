import pytest

from dice.live_types import DiceLiveError
from dice.virtual_currency import fixed_winner_selections


def test_fixed_winner_quote_is_complementary_and_integer_locked():
    quote = fixed_winner_selections(["blue", "clay"], 0.6234564)
    assert quote == {
        "blue": {"probability_millionths": 623456},
        "clay": {"probability_millionths": 376544},
    }


@pytest.mark.parametrize("probability", [0, 1, -0.1, 1.1])
def test_fixed_winner_quote_rejects_terminal_or_invalid_pregame_probability(probability):
    with pytest.raises(DiceLiveError):
        fixed_winner_selections(["blue", "clay"], probability)
