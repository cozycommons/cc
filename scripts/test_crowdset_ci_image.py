"""Check dependency image invalidation and registry-miss behavior without Docker."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('.github/images/crowdset-tests.Dockerfile',
          'backend/requirements-crowdset.txt', 'backend/crowdset/tests/requirements.txt')


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in (*INPUTS, 'scripts/crowdset-ci-image.sh'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.environment = {**os.environ, 'GITHUB_REPOSITORY': 'Example/Repo', 'CROWDSET_CI_PLATFORM': 'linux/amd64'}

    def run_script(self, command):
        return subprocess.check_output(
            ['bash', str(self.root / 'scripts/crowdset-ci-image.sh'), command],
            env=self.environment, text=True).strip()

    def test_every_build_input_invalidates_the_image(self):
        original = self.run_script('ref')
        self.assertTrue(original.startswith('ghcr.io/example/repo/crowdset-tests:deps-'))
        self.assertEqual(original, self.run_script('ref'))
        for name in INPUTS:
            with self.subTest(name=name):
                path = self.root / name
                content = path.read_bytes()
                path.write_bytes(content + b'\n# dependency changed\n')
                self.assertNotEqual(original, self.run_script('ref'))
                path.write_bytes(content)
        self.assertEqual(original, self.run_script('ref'))

    def test_architectures_have_separate_tags(self):
        amd64 = self.run_script('ref')
        self.environment['CROWDSET_CI_PLATFORM'] = 'linux/arm64'
        self.assertNotEqual(amd64, self.run_script('ref'))

    def test_registry_miss_builds_and_hit_does_not(self):
        executable = self.root / 'docker'
        executable.write_text('#!/bin/sh\necho "$1" >> "$DOCKER_LOG"\n'
                              'if [ "$1" = pull ]; then exit "$PULL_STATUS"; fi\n')
        executable.chmod(0o755)
        log = self.root / 'docker.log'
        self.environment.update(PATH=f'{self.root}{os.pathsep}{os.environ["PATH"]}',
                                DOCKER_LOG=str(log), PULL_STATUS='1')
        self.run_script('prepare')
        self.assertEqual(log.read_text().splitlines(), ['pull', 'build'])
        log.write_text('')
        self.environment['PULL_STATUS'] = '0'
        self.run_script('prepare')
        self.assertEqual(log.read_text().splitlines(), ['pull'])
