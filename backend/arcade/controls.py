"""Per-game input bindings and their resolution into a launch.

A binding maps extra physical inputs (keyboard codes and standard-layout
gamepad buttons) to a game action. The player frame turns each extra input into
the key the game itself listens to for that action, so the game's own keys keep
working. Game handling such as Sprint's DAS/ARR stays in the game adapter.
"""
import re

# Until games carry action metadata, Sprint's actions are named here.
SPRINT = "sprint"
SPRINT_ACTIONS = {"left": "Move left", "right": "Move right", "soft": "Soft drop", "hard": "Hard drop",
                  "cw": "Rotate right", "ccw": "Rotate left", "hold": "Hold"}
# Standard gamepad layout: 0 A, 1 B, 4 LB, 12-15 d-pad up/down/left/right.
DEFAULT_PAD = {"left": 14, "right": 15, "soft": 13, "hard": 12, "ccw": 0, "cw": 1, "hold": 4}
DEFAULT_KEYS = {"left": "KeyJ", "right": "KeyL", "soft": "KeyK"}
MAX_BUTTON = 31

GAME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ACTION_ID = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
KEY_CODE = re.compile(r"^[A-Za-z0-9]{1,24}$")

NAMED = {8: "Backspace", 9: "Tab", 13: "Enter", 16: "ShiftLeft", 17: "ControlLeft", 18: "AltLeft",
         27: "Escape", 32: "Space", 37: "ArrowLeft", 38: "ArrowUp", 39: "ArrowRight", 40: "ArrowDown",
         186: "Semicolon", 187: "Equal", 188: "Comma", 189: "Minus", 190: "Period", 191: "Slash",
         192: "Backquote", 219: "BracketLeft", 220: "Backslash", 221: "BracketRight", 222: "Quote"}
PUNCTUATION = {"Semicolon": ";", "Equal": "=", "Comma": ",", "Minus": "-", "Period": ".", "Slash": "/",
               "Backquote": "`", "BracketLeft": "[", "Backslash": "\\", "BracketRight": "]", "Quote": "'"}


def default_binding() -> dict:
    return {"keys": dict(DEFAULT_KEYS), "pad": dict(DEFAULT_PAD)}


def binding_for(settings: dict, game: str) -> dict:
    """The caller's binding for one game, or the defaults when none is saved."""
    return settings.get("controls", {}).get(game) or default_binding()


def code_of(key_code: int) -> str | None:
    """DOM `code` for a Flash/legacy keyCode, as the browser would report it."""
    if 65 <= key_code <= 90:
        return "Key" + chr(key_code)
    if 48 <= key_code <= 57:
        return "Digit" + chr(key_code)
    if 96 <= key_code <= 105:
        return "Numpad" + str(key_code - 96)
    return NAMED.get(key_code)


def key_of(code: str) -> str:
    """DOM `key` for a code. Ruffle reads `key`, so ArrowLeft must stay ArrowLeft."""
    if re.fullmatch(r"Key[A-Z]", code):
        return code[3:].lower()
    if re.fullmatch(r"(Digit|Numpad)\d", code):
        return code[-1]
    if code == "Space":
        return " "
    if code in PUNCTUATION:
        return PUNCTUATION[code]
    # Only modifiers collapse sides: ShiftLeft -> Shift.
    return re.sub(r"^(Shift|Control|Alt|Meta)(Left|Right)$", r"\1", code)


def validate(controls: dict) -> str | None:
    """Return an error message for a malformed `controls` setting, else None."""
    if len(controls) > 64:
        return "Too many games in control settings"
    for game, binding in controls.items():
        if not GAME_ID.match(game) or not isinstance(binding, dict) or not set(binding) <= {"keys", "pad"}:
            return "Invalid control settings"
        keys, pad = binding.get("keys", {}), binding.get("pad", {})
        if not isinstance(keys, dict) or not isinstance(pad, dict) or len(keys) > 32 or len(pad) > 32:
            return "Invalid control settings"
        actions = SPRINT_ACTIONS.keys() if game == SPRINT else None
        for bound in (keys, pad):
            if any(not ACTION_ID.match(action) or (actions is not None and action not in actions) for action in bound):
                return "Unknown game action"
        if any(not isinstance(code, str) or not KEY_CODE.match(code) for code in keys.values()) \
                or len(set(keys.values())) != len(keys):
            return "Choose a distinct keyboard key for each action"
        if any(type(button) is not int or not 0 <= button <= MAX_BUTTON for button in pad.values()) \
                or len(set(pad.values())) != len(pad):
            return "Choose a distinct gamepad button for each action"
    return None


def resolve(game_keys: dict[str, int], binding: dict) -> dict:
    """Launch input for the player frame.

    `targets` is what each action's synthetic key looks like to the game.
    An extra key that is already one of the game's own keys is skipped, so the
    game's in-movie controls always win over a stale binding.
    """
    targets = {}
    for action, key_code in game_keys.items():
        code = code_of(key_code)
        if code:
            targets[action] = {"code": code, "key": key_of(code), "key_code": key_code}
    own = {target["code"] for target in targets.values()}
    keys = {code: action for action, code in binding.get("keys", {}).items()
            if action in targets and code not in own}
    buttons = {str(button): action for action, button in binding.get("pad", {}).items() if action in targets}
    return {"targets": targets, "keys": keys, "buttons": buttons}


def describe(game_keys: dict[str, int], binding: dict) -> dict:
    """Bindable actions with the game's own key, for the settings table."""
    return {"game": SPRINT, "binding": binding,
            "actions": [{"id": action, "name": name, "game_key": code_of(game_keys.get(action, 0))}
                        for action, name in SPRINT_ACTIONS.items()]}
