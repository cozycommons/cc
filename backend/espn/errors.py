"""Short operational failures without echoed URLs, headers or credentials."""
import re

# A sensitive key drops everything after it: quoting and multiword header values vary too much to trim.
_SCRUB = ((re.compile(r'(?i)\b(espn_s2|swid|cookie|set-cookie|authorization|x-fantasy-filter|headers?)\b.*'), r'\1 <redacted>'),
          (re.compile(r'https?://\S+'), '<url>'),
          (re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'), '<id>'),
          (re.compile(r'[A-Za-z0-9%+/=_-]{40,}'), '<redacted>'))


def scrub(text, *, limit=160):
    """One short line with URLs, cookies, headers and long tokens removed."""
    text = ' '.join(str(text).split())
    for pattern, replacement in _SCRUB:
        text = pattern.sub(replacement, text)
    return text[:limit]


def failure_reason(exc):
    text = scrub(exc)
    return f'{type(exc).__name__}: {text}' if text else type(exc).__name__
