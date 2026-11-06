"""Keep advisory acceptance narrow, dated and temporary."""
import datetime as dt
from pathlib import Path
import tomllib
import unittest


def validate_policy(data, today):
    if set(data) - {'IgnoredVulns'}:
        raise ValueError('Only IgnoredVulns entries are allowed; no PackageOverrides')
    for entry in data.get('IgnoredVulns', []):
        if not entry.get('id', '').strip() or not entry.get('reason', '').strip():
            raise ValueError('Every ignore needs an id and non-empty reason')
        expiry = entry.get('ignoreUntil')
        if not isinstance(expiry, dt.date) or not today <= expiry <= today + dt.timedelta(days=30):
            raise ValueError('ignoreUntil must be an unexpired date within 30 days')


class AdvisoryPolicyTests(unittest.TestCase):
    def test_repository_policy(self):
        path = Path(__file__).resolve().parents[1] / 'osv-scanner.toml'
        validate_policy(tomllib.loads(path.read_text()), dt.datetime.now(dt.timezone.utc).date())

    def test_rejects_undated_or_broad_ignores(self):
        today = dt.date(2026, 11, 5)
        good = dict(id='TEST-1', reason='reviewed 2026-11-05, synthetic test', ignoreUntil=today)
        validate_policy({'IgnoredVulns': [good]}, today)
        for entry in ({}, good | {'reason': ' '}, good | {'id': ''},
                      good | {'ignoreUntil': today + dt.timedelta(days=31)},
                      good | {'ignoreUntil': today - dt.timedelta(days=1)}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                validate_policy({'IgnoredVulns': [entry]}, today)
        with self.assertRaisesRegex(ValueError, 'PackageOverrides'):
            validate_policy({'PackageOverrides': []}, today)
