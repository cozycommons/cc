"""The Sink protocol: how applications plug into ig_logger.

A sink is an application that does something with Instagram posts for a
user — Beli (auto-bookmarking restaurants) is the first. To add a sink:

  1. Create `ig_logger/sinks/<name>/` with your implementation.
  2. Implement the Sink protocol below.
  3. Register it: `from ig_logger.sinks import register_sink` then
     `register_sink(MySink())` at the bottom of your sink module, and
     import the module from `ig_logger/runner.py`.

The runner calls `enabled_for(account)` per account and `process(posts,
account)` for each enabled sink. `process` receives normalized posts
(see `ig_logger/models.py`) already filtered to what's new for that
account's subscription watermark, and must return a JSON-serializable
digest dict. It must never raise on per-post failures — report them in
the digest as skipped.
"""

from __future__ import annotations

from typing import Protocol


class Sink(Protocol):
    name: str

    def enabled_for(self, account: dict) -> bool:
        """Whether this sink is enabled for the account row."""
        ...

    def process(self, posts: list[dict], account: dict) -> dict:
        """Process new posts for one account. Returns a digest dict."""
        ...


SINKS: dict[str, Sink] = {}


def register_sink(sink: Sink) -> None:
    SINKS[sink.name] = sink


def get_sink(name: str) -> Sink | None:
    return SINKS.get(name)
