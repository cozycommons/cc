import datetime as dt
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import tempfile
import urllib.error
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
            'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/example': {'version': '1.0.0', 'resolved': 'https://registry.npmjs.org/example/-/example-1.0.0.tgz', 'integrity': 'sha512-test'}}}))
        self.stack.enter_context(patch.object(age.subprocess, 'check_output', return_value='package-lock.json\n'))
        times = {'1.0.0': '2026-10-29T00:00:00Z'}
        metadata = {'time': times, 'versions': {'1.0.0': {'dist': {'tarball': 'https://registry.npmjs.org/example/-/example-1.0.0.tgz', 'integrity': 'sha512-test'}}}}
        self.stack.enter_context(patch.object(age, 'registry_metadata', return_value=metadata))
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

    def test_npm_artifact_mismatch_even_with_old_version(self):
        self.stack.enter_context(patch.object(age.subprocess, 'check_output', return_value='package-lock.json\n'))
        self.stack.enter_context(patch.object(age, 'registry_metadata', return_value={
            'time': {'1.3.0': '2016-01-01T00:00:00Z'},
            'versions': {'1.3.0': {'dist': {'tarball': 'https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz', 'integrity': 'sha512-old'}}}}))
        good = dict(version='1.3.0', resolved='https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz', integrity='sha512-old')
        for changes in ({'resolved': 'https://registry.npmjs.org/fresh/-/fresh-1.0.0.tgz'}, {'integrity': 'sha512-new'}, {'resolved': None}, {'integrity': None}):
            (self.root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {'node_modules/left-pad': good | changes}}))
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'does not match registry artifact'):
                age.check_npm()

    def test_python_rejects_non_registry_sources(self):
        path = self.root / 'requirements.in'
        for source in ('pkg @ https://example.com/pkg.whl', 'git+https://example.com/repo', './local', '-r other.in', 'https://example.com/pkg.whl', 'pkg @ file:///tmp/pkg'):
            path.write_text('# uv-exclude-newer: 2026-10-28T00:00:00Z\n' + source)
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'only registry'):
                age.check_python(path)

    def test_python_exception_is_one_exact_package(self):
        path = self.root / 'requirements.in'
        path.write_text('# uv-exclude-newer: 2026-10-28T00:00:00Z\nexample==1.0.0\nother>=2\n')
        entry = dict(ecosystem='pypi', name='example', version='1.0.0', cutoff='2026-11-04T00:00:00Z',
                     reason='synthetic security fix', reviewed_by='test reviewer', reviewed_on='2026-11-05', expires='2026-11-06')
        (self.root / 'dependency-age-exceptions.json').write_text(json.dumps([entry]))
        self.assertEqual(age.check_python(path), {'example': entry['cutoff']})
        path.write_text(path.read_text().replace('example==1.0.0', 'example>=1'))
        with self.assertRaisesRegex(ValueError, 'exact pin'):
            age.check_python(path)
        path.write_text('# uv-exclude-newer: 2026-11-04T00:00:00Z\nexample==1.0.0')
        with self.assertRaisesRegex(ValueError, 'at least 7 days'):
            age.check_python(path)

    def test_npm_change_selection(self):
        for paths, expected in [('docs/readme.md\n', False), ('frontend/package-lock.json\n', True),
                                ('dependency-age-exceptions.json\n', True), ('package-lock.json\n', True)]:
            with patch.object(age.subprocess, 'check_output', return_value=paths):
                self.assertEqual(age.npm_changed('base'), expected)
        self.assertTrue(age.npm_changed(''))

    def test_registry_retry_and_cache(self):
        self.stack.enter_context(patch.object(age.subprocess, 'check_output', return_value='synthetic-head'))
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"time": {}, "versions": {}}'
        self.stack.enter_context(patch.object(age.time, 'sleep'))
        for error in (urllib.error.URLError('timeout'), urllib.error.HTTPError('url', 429, 'rate', {}, None), urllib.error.HTTPError('url', 503, 'unavailable', {}, None)):
            with patch.object(age.urllib.request, 'urlopen', side_effect=[error, error, response]) as request:
                age.registry_metadata(str(error))
                self.assertEqual(request.call_count, 3)
                age.registry_metadata(str(error))
                self.assertEqual(request.call_count, 3)
        with patch.object(age.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')) as request:
            with self.assertRaises(urllib.error.URLError):
                age.registry_metadata('offline')
            self.assertEqual(request.call_count, 3)
        with patch.object(age.urllib.request, 'urlopen', side_effect=urllib.error.HTTPError('url', 404, 'missing', {}, None)) as request:
            with self.assertRaises(urllib.error.HTTPError):
                age.registry_metadata('missing')
            self.assertEqual(request.call_count, 1)


class ResolverIntegrationTests(unittest.TestCase):
    def test_uv_enforces_global_and_package_cutoffs(self):
        import shutil
        import subprocess
        if not shutil.which('uv'):
            self.skipTest('requires the CI-pinned uv tool')
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            for name in ('lock-backend-requirements.sh', 'check-dependency-age.py'):
                shutil.copy(source / 'scripts' / name, root / 'scripts' / name)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                            'commit', '--allow-empty', '-qm', 'synthetic age probe'], check=True)
            committed = int(subprocess.check_output(['git', '-C', str(root), 'log', '-1', '--format=%ct']))
            today = dt.datetime.fromtimestamp(committed, dt.timezone.utc).date().isoformat()
            (root / 'requirements.in').write_text(
                '# uv-version: 0.13.7\n# uv-exclude-newer: 2024-01-01T00:00:00Z\nsix==1.17.0\n')
            exception = root / 'dependency-age-exceptions.json'
            exception.write_text('[]')
            command = ['bash', str(root / 'scripts/lock-backend-requirements.sh'), 'requirements.in', 'requirements.txt']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('six', result.stderr)
            exception.write_text(json.dumps([dict(ecosystem='pypi', name='six', version='1.17.0',
                cutoff='2025-01-01T00:00:00Z', reason='synthetic test only', reviewed_by='test',
                reviewed_on=today, expires=today)]))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('six==1.17.0', (root / 'requirements.txt').read_text())
