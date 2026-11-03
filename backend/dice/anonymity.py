"""Anonymous Dice players, shown as a reshuffled animal on recorded results.

A player who turns on anonymous play still counts everywhere (ratings, duos,
leaderboards, streaks). Responses about recorded results replace their user id
with an opaque alias and their name with "Anonymous <Animal>". Aliases are
keyed by a per-visit seed the browser sends, so one visit sees consistent
names across every section and a new visit gets a fresh shuffle; without the
header every request is shuffled independently. Player pickers, live games and
the player's own views keep real names.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

SEED_HEADER = "X-Dice-View-Seed"
ALIAS_PREFIX = "anon-"
_SEED_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

ANIMALS = (
    "Aardvark", "Alpaca", "Armadillo", "Axolotl", "Badger", "Beaver", "Bison", "Capybara",
    "Chameleon", "Cheetah", "Chinchilla", "Coyote", "Crane", "Dingo", "Dolphin", "Dormouse",
    "Falcon", "Ferret", "Flamingo", "Fox", "Gazelle", "Gecko", "Giraffe", "Hedgehog",
    "Heron", "Hippo", "Ibex", "Iguana", "Jackal", "Kangaroo", "Kiwi", "Koala",
    "Lemur", "Llama", "Lynx", "Manatee", "Meerkat", "Mongoose", "Moose", "Narwhal",
    "Ocelot", "Octopus", "Okapi", "Orca", "Otter", "Panda", "Pangolin", "Pelican",
    "Penguin", "Platypus", "Puffin", "Quokka", "Raccoon", "Raven", "Salamander", "Seal",
    "Sloth", "Tapir", "Toucan", "Turtle", "Walrus", "Wombat", "Yak", "Zebra",
)


def _secret() -> bytes:
    # Shared by every API worker so one seed gives the same aliases everywhere.
    configured = os.getenv("DICE_ANONYMITY_SECRET") or os.getenv("SUPABASE_SERVICE_KEY") or ""
    return hmac.new(b"dice-anonymity/v1", configured.encode("utf-8"), hashlib.sha256).digest()


_SECRET = _secret()


def view_seed(header_value: str | None) -> str:
    if header_value and _SEED_PATTERN.fullmatch(header_value):
        return header_value
    return secrets.token_hex(8)


def _digest(seed: str, value: str) -> str:
    return hmac.new(_SECRET, f"{seed}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class Anonymizer:
    """Maps anonymous players' real ids to (alias id, alias name) for one seed."""

    aliases: dict[str, tuple[str, str]] = field(default_factory=dict)

    @classmethod
    def build(cls, anonymous_ids: set[str], seed: str, exempt: set[str] | None = None) -> "Anonymizer":
        ids = sorted(anonymous_ids - (exempt or set()), key=lambda user_id: _digest(seed, user_id))
        animals = sorted(ANIMALS, key=lambda animal: _digest(seed, animal))
        aliases = {}
        for index, user_id in enumerate(ids):
            animal = animals[index % len(animals)]
            if index >= len(animals):
                animal = f"{animal} {index // len(animals) + 1}"
            aliases[user_id] = (ALIAS_PREFIX + _digest(seed, user_id)[:16], f"Anonymous {animal}")
        return cls(aliases)

    @property
    def active(self) -> bool:
        return bool(self.aliases)

    def alias_id(self, value: str) -> str:
        if value in self.aliases:
            return self.aliases[value][0]
        # Composite ids (e.g. duo ids embed both members) are rewritten in place.
        for user_id, (alias, _) in self.aliases.items():
            if user_id in value:
                value = value.replace(user_id, alias)
        return value

    def real_duo_id(self, requested: str, candidates) -> str | None:
        """The real duo whose aliased id is `requested`, or None. A real id that
        names an anonymous player never matches, since it aliases to something else."""
        return next((candidate for candidate in candidates if self.alias_id(candidate) == requested), None)

    def scrub(self, value: Any) -> Any:
        """Return a JSON-shaped copy with every anonymous identity replaced."""
        if not self.active:
            return value
        if isinstance(value, dict):
            original_user_id = value.get("user_id")
            # Keys too: e.g. recorded_stats.players is keyed by user id.
            scrubbed = {self.scrub(key): self.scrub(item) for key, item in value.items()}
            if isinstance(original_user_id, str) and original_user_id in self.aliases:
                if "display_name" in scrubbed:
                    scrubbed["display_name"] = self.aliases[original_user_id][1]
                if "avatar_url" in scrubbed:
                    scrubbed["avatar_url"] = None
            return scrubbed
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.scrub(item) for item in value)
        if isinstance(value, str):
            return self.alias_id(value)
        return value


def anonymous_user_ids(supabase) -> set[str]:
    rows = (
        supabase.table("dice_profiles")
        .select("user_id")
        .eq("is_anonymous", True)
        .execute()
        .data
        or []
    )
    return {row["user_id"] for row in rows}


def anonymizer_for(request, viewer_id: str | None = None) -> Anonymizer:
    ids = anonymous_user_ids(request.app.state.supabase)
    if not ids:
        return Anonymizer()
    seed = view_seed(request.headers.get(SEED_HEADER))
    return Anonymizer.build(ids, seed, exempt={viewer_id} if viewer_id else None)


def dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [dump(item) for item in value]
    return value
