"""ig_logger: a generic Instagram-to-sink logging platform.

Any user can subscribe to any public Instagram source (account or post
author) and route what gets pulled into any registered sink. Sinks are
applications that live under `ig_logger/sinks/` and implement the Sink
protocol (see `ig_logger/sinks/__init__.py`).

The first sink is Beli (`sinks/beli/`): it watches @beli_eats and
auto-bookmarks confident restaurant mentions into each opted-in account's
Beli "Want to Try".

Fetching model (unchanged from the Beli-only days): CC never touches
Instagram. A fetch box on the operator's VM polls the scan-job queue,
fetches Instagram locally through a native session, and POSTs the raw
posts back. CC then fans the posts out to every subscribed account and
every enabled sink.
"""
