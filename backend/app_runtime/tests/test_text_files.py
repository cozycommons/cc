"""Filesystem outcome probes, using real files and a separate helper process."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from app_runtime import text_files as tf
from app_runtime.docker_runtime import Runtime


def sha(data):
    return hashlib.sha256(data).hexdigest()


def edit(path, data, old, new):
    return {'path': path, 'expected_sha256': sha(data), 'edits': [{'old_text': old, 'new_text': new}]}


def test_real_helper_preserves_crlf_mode_and_missing_final_newline(tmp_path):
    name = "spaces ' quotes ☕.py"
    original = b'#!/usr/bin/python\r\nprint("before")'
    path = tmp_path / name
    path.write_bytes(original)
    path.chmod(0o751)
    payload = tmp_path / 'request.json'
    payload.write_text(json.dumps({'operation': 'edit', 'request': {'files': [edit(name, original, 'before', 'after')]}}))
    result = subprocess.run([sys.executable, tf.__file__, str(tmp_path), str(payload)], capture_output=True, timeout=5)
    assert result.returncode == 0 and json.loads(result.stdout)['ok']
    assert path.read_bytes() == b'#!/usr/bin/python\r\nprint("after")'
    assert path.stat().st_mode & 0o777 == 0o751
    read = tf.operate(tmp_path, 'read', {'files': [{'path': name}]})['files'][0]
    assert read['newline_style'] == 'CRLF' and not read['has_final_newline']
    assert read['whole_file'] and read['sha256'] == sha(path.read_bytes())


def test_batch_preflight_conflict_and_ambiguity_leave_all_files_unchanged(tmp_path):
    (tmp_path / 'a').write_bytes(b'first')
    (tmp_path / 'b').write_bytes(b'repeat repeat')
    request = {'files': [edit('a', b'first', 'first', 'changed'), edit('b', b'repeat repeat', 'repeat', 'once')]}
    with pytest.raises(tf.TextError, match='more than once'):
        tf.operate(tmp_path, 'edit', request)
    assert (tmp_path / 'a').read_bytes() == b'first'
    assert (tmp_path / 'b').read_bytes() == b'repeat repeat'
    request['files'][1] = edit('b', b'outdated', 'repeat repeat', 'changed')
    with pytest.raises(tf.TextError) as error:
        tf.operate(tmp_path, 'edit', request)
    assert error.value.code == 'CONFLICT'
    assert (tmp_path / 'a').read_bytes() == b'first'


def test_create_only_and_cas_full_write(tmp_path):
    req = {'path': 'new', 'content': 'α\r\nlast', 'expected_sha256': None}
    result = tf.operate(tmp_path, 'write', req)
    assert result['created'] and (tmp_path / 'new').read_bytes() == 'α\r\nlast'.encode()
    with pytest.raises(tf.TextError) as error:
        tf.operate(tmp_path, 'write', req)
    assert error.value.code == 'ALREADY_EXISTS'
    req.update(content='replacement', expected_sha256=result['sha256'])
    tf.operate(tmp_path, 'write', req)
    assert (tmp_path / 'new').read_bytes() == b'replacement'
    assert not list(tmp_path.glob('.cc-text-*'))


def test_read_budget_does_not_starve_small_later_file_or_break_utf8(tmp_path):
    (tmp_path / 'huge').write_text('🍵' * 200000)
    (tmp_path / 'small').write_bytes(b'important test\r\n')
    result = tf.operate(tmp_path, 'read', {'files': [{'path': 'huge'}, {'path': 'small'}], 'max_output_bytes': 101})
    large, small = result['files']
    assert small['content'] == 'important test\r\n' and small['whole_file']
    assert large['truncated'] and len(large['content'].encode()) <= 85
    assert result['content_bytes'] <= 101
    assert large['sha256'] == sha((tmp_path / 'huge').read_bytes())


def test_paths_links_binary_and_bounds_are_rejected_without_mutation(tmp_path):
    (tmp_path / 'real').write_bytes(b'original')
    (tmp_path / 'sym').symlink_to('real')
    (tmp_path / 'dirsym').symlink_to(tmp_path, target_is_directory=True)
    os.link(tmp_path / 'real', tmp_path / 'hard')
    (tmp_path / 'binary').write_bytes(b'\xffsecret')
    (tmp_path / 'huge').write_bytes(b'x' * (tf.FILE_LIMIT + 1))
    for path, code in [('sym', 'NOT_REGULAR_FILE'), ('dirsym/real', 'NOT_REGULAR_FILE'), ('hard', 'NOT_REGULAR_FILE'), ('binary', 'INVALID_UTF8'), ('huge', 'FILE_TOO_LARGE')]:
        result = tf.operate(tmp_path, 'read', {'files': [{'path': path}]})
        assert result['files'][0]['error'] == tf.TextError(code).detail()
    for path in ['../real', '/real', 'a//real', './real']:
        with pytest.raises(tf.TextError) as error:
            tf.operate(tmp_path, 'write', {'path': path, 'content': 'bad', 'expected_sha256': None})
        assert error.value.code == 'INVALID_PATH'
    assert (tmp_path / 'real').read_bytes() == b'original'
    with pytest.raises(tf.TextError) as error:
        tf.operate(tmp_path, 'write', {'path': 'x', 'content': 'a' * (tf.FILE_LIMIT + 1), 'expected_sha256': None})
    assert error.value.code == 'INPUT_TOO_LARGE'


def test_late_replacement_failure_is_explicit_partial_not_transaction(tmp_path, monkeypatch):
    for path in ['a', 'b']:
        (tmp_path / path).write_bytes(b'original')
    replace = tf.os.replace
    def fail_second(src, dst, **kwargs):
        if dst == 'b':
            raise OSError('secret detail must never be returned')
        return replace(src, dst, **kwargs)
    monkeypatch.setattr(tf.os, 'replace', fail_second)
    with pytest.raises(tf.TextError) as error:
        tf.operate(tmp_path, 'edit', {'files': [edit(path, b'original', 'original', 'changed') for path in ['a', 'b']]})
    assert error.value.code == 'PARTIAL_WRITE'
    assert 'secret' not in str(error.value)
    assert (tmp_path / 'a').read_bytes() == b'changed'
    assert (tmp_path / 'b').read_bytes() == b'original'
    assert not list(tmp_path.glob('.cc-text-*'))


def test_runtime_stages_user_content_and_cleans_up_on_failure(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env', lambda: client)
    runtime = Runtime()
    commands = []
    def execute(name, argv, seconds, collect):
        commands.append(argv)
        assert 'private unique payload' not in '\n'.join(argv)
        collect(b'{"ok":false,"error":{"code":"CONFLICT","message":"untrusted secret"}}')
        return 0
    monkeypatch.setattr(runtime, '_exec', execute)
    with pytest.raises(tf.TextError) as error:
        runtime.text('trip', 'write', {'path': 'x', 'content': 'private unique payload', 'expected_sha256': None})
    assert error.value.detail() == tf.TextError('CONFLICT').detail()
    assert commands[0][:4] == ['/usr/bin/timeout', '--signal=TERM', '--kill-after=1s', '15s']
    client.containers.get.return_value.put_archive.assert_called_once()
    assert client.containers.get.return_value.exec_run.call_args.args[0][:2] == ['/bin/rm', '-f']


@pytest.mark.parametrize('batch', [False, True])
def test_overlapping_matches_are_ambiguous_and_leave_entire_batch_unchanged(tmp_path, batch):
    (tmp_path / 'first').write_bytes(b'before')
    (tmp_path / 'overlap').write_bytes(b'aaa')
    files = [edit('overlap', b'aaa', 'aa', 'X')]
    if batch:
        files.insert(0, edit('first', b'before', 'before', 'after'))
    with pytest.raises(tf.TextError) as error:
        tf.operate(tmp_path, 'edit', {'files': files})
    assert error.value.code == 'AMBIGUOUS_MATCH'
    assert (tmp_path / 'first').read_bytes() == b'before'
    assert (tmp_path / 'overlap').read_bytes() == b'aaa'
    assert not list(tmp_path.glob('.cc-text-*'))
