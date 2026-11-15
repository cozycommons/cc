"""Precision file helper on a real isolated app volume; no published ports."""
import hashlib
import os

import pytest

from app_runtime import text_files
from app_runtime.tests.test_docker_ergonomics import sandbox

pytestmark = pytest.mark.skipif(os.environ.get('APPS_DOCKER_TESTS') != '1', reason='Requires local Docker')


def test_injected_text_helper_modes_conflicts_and_large_request(sandbox):
    data = ('line one\r\nUnicode 🌿 and apostrophe\'s\r\n').encode()
    created = sandbox.text('trip', 'write', {'path': 'example.txt', 'content': data.decode(), 'expected_sha256': None})
    sha = hashlib.sha256(data).hexdigest()
    assert created['sha256'] == sha
    sandbox.container('trip').exec_run(['chmod', '755', '/workspace/example.txt'])
    read = sandbox.text('trip', 'read', {'files': [{'path': 'example.txt'}], 'max_output_bytes': 65536})
    assert read['files'][0]['content'].encode() == data
    assert read['files'][0]['newline_style'] == 'CRLF'
    sandbox.text('trip', 'edit', {'files': [{'path': 'example.txt', 'expected_sha256': sha,
        'edits': [{'old_text': 'line one', 'new_text': 'line two'}]}]})
    assert sandbox.container('trip').exec_run(['test', '-x', '/workspace/example.txt']).exit_code == 0
    with pytest.raises(text_files.TextError) as exc:
        sandbox.text('trip', 'write', {'path': 'example.txt', 'content': 'bad', 'expected_sha256': sha})
    assert exc.value.code == 'CONFLICT'
    # Staged archive request avoids OS single-argument limits.
    big = 'x' * 300000
    sandbox.text('trip', 'write', {'path': 'large.txt', 'content': big, 'expected_sha256': None})
    limited = sandbox.text('trip', 'read', {'files': [{'path': 'large.txt'}], 'max_output_bytes': 128})
    assert len(limited['files'][0]['content'].encode()) == 128
    assert limited['files'][0]['sha256'] == hashlib.sha256(big.encode()).hexdigest()
    assert limited['files'][0]['truncated'] and not limited['files'][0]['whole_file']
    sandbox.container('trip').exec_run(['ln', '-s', '/etc/hosts', '/workspace/escape'])
    rejected = sandbox.text('trip', 'read', {'files': [{'path': 'escape'}]})
    assert rejected['files'][0]['error']['code'] in {'INVALID_PATH', 'NOT_REGULAR_FILE'}
