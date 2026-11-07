"""VITAL Brooklyn's live headcount from Safespace, served as a bare number in plain text (no auth)."""
from urllib.request import urlopen

URL = 'https://display.safespace.io/value/live/a7796f34'
TIMEOUT_S = 4
MAX_BYTES = 64


class FeedError(Exception):
    pass


def fetch():
    """Return the live headcount; raises FeedError, without the response text, when the feed is down or garbled."""
    try:
        with urlopen(URL, timeout=TIMEOUT_S) as response:
            body = response.read(MAX_BYTES + 1)
    except OSError as error:
        raise FeedError(type(error).__name__) from None
    text = body.decode(errors='replace').strip()
    if len(body) > MAX_BYTES or not text.isdigit():
        raise FeedError('unexpected response')
    return int(text)
