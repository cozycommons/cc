import datetime as dt
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('age', Path(__file__).with_name('check-dependency-age.py'))
age = importlib.util.module_from_spec(spec)
spec.loader.exec_module(age)
NOW = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'dependency-age-exceptions.json').write_text('[]')
        self.stack.enter_context(patch.object(age, 'ROOT', self.root))
        self.stack.enter_context(patch.object(age, 'commit_time', return_value=NOW))

    def test_python_boundary_and_fresh_failure(self):
        path = self.root / 'requirements.in'
        path.write_text('# uv-exclude-newer: 2026-10-29T00:00:00Z\n')
        age.check_python(path)
        path.write_text('# uv-exclude-newer: 2026-10-29T00:00:01Z\n')
        with self.assertRaisesRegex(ValueError, 'at least 7 days'):
            age.check_python(path)

    def test_npm_registry_time_and_explicit_exception(self):
        (self.root / 'package-lock.json').write_text(json.dumps({
            'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/example': {'version': '1.0.0'}}}))
        self.stack.enter_context(patch.object(age.subprocess, 'check_output', return_value='package-lock.json\n'))
        times = {'1.0.0': '2026-10-29T00:00:00Z'}
        self.stack.enter_context(patch.object(age, 'registry_times', return_value=times))
        age.check_npm()
        times['1.0.0'] = '2026-11-04T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'younger than 7 days'):
            age.check_npm()
        entry = dict(ecosystem='npm', name='example', version='1.0.0',
                     reason='synthetic security fix', reviewed_by='test reviewer',
                     reviewed_on='2026-11-05', expires='2026-11-06')
        (self.root / 'dependency-age-exceptions.json').write_text(json.dumps([entry]))
        age.check_npm()
        entry['expires'] = '2026-11-04'
        (self.root / 'dependency-age-exceptions.json').write_text(json.dumps([entry]))
        with self.assertRaisesRegex(ValueError, 'expired'):
            age.check_npm()

    def test_python_missing_or_relative_cutoff_fails(self):
        path = self.root / 'requirements.in'
        for text in ('', '# uv-exclude-newer: 7 days\n', '# uv-exclude-newer: 2026-10-28\n'):
            path.write_text(text)
            with self.assertRaises(ValueError):
                age.check_python(path)
