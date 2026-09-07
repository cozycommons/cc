from dice.virtual_currency import LEDGER_PAGE_SIZE, tournament_virtual_leaderboard


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, tables, ranges, table_name):
        self.tables = tables
        self.ranges = ranges
        self.table_name = table_name
        self.start = None
        self.end = None

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def range(self, start, end):
        self.start = start
        self.end = end
        self.ranges.append((start, end))
        return self

    def execute(self):
        rows = self.tables[self.table_name]
        if self.start is not None:
            rows = rows[self.start : self.end + 1]
        return _Response(rows)


class _Client:
    def __init__(self, tables):
        self.tables = tables
        self.ranges = []

    def table(self, name):
        return _Query(self.tables, self.ranges, name)


def test_leaderboard_sums_every_ledger_page_and_includes_zero_balance_entrants():
    ledger = [{"user_id": "u1", "amount": 1} for _ in range(LEDGER_PAGE_SIZE)]
    ledger += [{"user_id": "u1", "amount": -200}, {"user_id": "u2", "amount": 900}]
    client = _Client({
        "dice_tournament_enrollments": [{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "u3"}],
        "dice_profiles": [
            {"user_id": "u1", "display_name": "Alice"},
            {"user_id": "u2", "display_name": "Bea"},
            {"user_id": "u3", "display_name": "Cam"},
        ],
        "dice_virtual_ledger": ledger,
    })

    result = tournament_virtual_leaderboard(client, "tournament-1")

    assert [(row["user_id"], row["balance"]) for row in result] == [
        ("u2", 900), ("u1", 800), ("u3", 0),
    ]
    assert [row["rank"] for row in result] == [1, 2, 3]
    assert client.ranges == [(0, 999), (1000, 1999)]


def test_leaderboard_breaks_equal_balances_by_stable_player_id():
    client = _Client({
        "dice_tournament_enrollments": [{"user_id": "u2"}, {"user_id": "u1"}],
        "dice_profiles": [
            {"user_id": "u1", "display_name": "Zed"},
            {"user_id": "u2", "display_name": "Amy"},
        ],
        "dice_virtual_ledger": [
            {"user_id": "u2", "amount": 10}, {"user_id": "u1", "amount": 10},
        ],
    })

    result = tournament_virtual_leaderboard(client, "tournament-1")

    assert [row["user_id"] for row in result] == ["u1", "u2"]
