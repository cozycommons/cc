from request_telemetry import dice_live_request_tags


def test_tags_live_command_attempts_for_log_correlation():
    tags = dice_live_request_tags(
        "/dice/live/games/match-1/commands",
        {
            "x-dice-live-attempt": "hedge",
            "x-dice-live-operation": "live-command.1",
        },
    )
    assert tags == {
        "dice_live_attempt": "hedge",
        "dice_live_operation_id": "live-command.1",
    }


def test_ignores_untrusted_or_unrelated_request_tags():
    assert dice_live_request_tags(
        "/dice/live/games/match-1/commands",
        {"x-dice-live-attempt": "many", "x-dice-live-operation": "bad value"},
    ) == {}
    assert dice_live_request_tags(
        "/dice/live/games/match-1",
        {"x-dice-live-attempt": "original", "x-dice-live-operation": "command-1"},
    ) == {}
