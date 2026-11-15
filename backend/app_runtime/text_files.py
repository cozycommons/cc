"""Bounded text operations injected into an existing app container.

Only the manager invokes this helper. Structured operations serialize with the
manager's per-app lock; arbitrary shell writers do not honor that lock. Directory
FDs and no-follow opens reject ordinary symlink/path attacks, but do not establish
an isolation boundary against a hostile process with the same app privileges.
"""
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

FILE_LIMIT = 1024 * 1024
REQUEST_LIMIT = 2 * 1024 * 1024
CONTENT_LIMIT = 64 * 1024
METADATA_LIMIT = 32 * 1024
RESPONSE_LIMIT = 512 * 1024
HELPER_SECONDS = 15
HELPER_WALL_TIMEOUT = '15s'
EXEC_SECONDS = 20
MAX_READ_FILES = 32
MAX_EDIT_FILES = 16
MAX_EDITS = 64
PATH_LIMIT = 512
SHA = re.compile(r'^[a-f0-9]{64}$')
ERRORS = {
    'INVALID_ARGUMENT': 'Invalid text operation arguments',
    'INVALID_PATH': 'Use a bounded workspace-relative path without dot components',
    'NOT_FOUND': 'File or parent directory does not exist',
    'NOT_REGULAR_FILE': 'Text operations require regular files without symlinks or hardlinks',
    'FILE_TOO_LARGE': 'Text file exceeds the 1 MiB limit; use shell or binary transfer',
    'INPUT_TOO_LARGE': 'Text request exceeds its input limit',
    'INVALID_UTF8': 'Text operations require strict UTF-8 content',
    'CONFLICT': 'File changed; reread before editing',
    'ALREADY_EXISTS': 'Create refused because the file already exists',
    'AMBIGUOUS_MATCH': 'Exact edit matched more than once; include unique surrounding context',
    'MATCH_NOT_FOUND': 'Exact edit text was not found; reread content and preserve its newlines',
    'TEXT_IO_ERROR': 'Text operation could not access the file',
    'PARTIAL_WRITE': 'A batch write failed; some files may have changed; reread before retrying',
    'TEXT_RUNTIME_ERROR': 'Text helper failed; inspect app state before retrying a write',
    'TEXT_OUTPUT_LIMIT': 'Text helper exceeded its response limit; inspect app state before retrying',
}


class TextError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'TEXT_RUNTIME_ERROR'
        super().__init__(ERRORS[self.code])

    def detail(self):
        return {'code': self.code, 'message': ERRORS[self.code]}


def fail(code):
    raise TextError(code)


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        fail('INVALID_ARGUMENT')


def integer(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        fail('INVALID_ARGUMENT')
    return value


def text(value):
    if not isinstance(value, str):
        fail('INVALID_ARGUMENT')
    try:
        return value.encode('utf-8', 'strict')
    except UnicodeError:
        fail('INVALID_UTF8')


def relative_path(value):
    encoded = text(value)
    if not encoded or len(encoded) > PATH_LIMIT or '\x00' in value or value.startswith('/'):
        fail('INVALID_PATH')
    parts = value.split('/')
    if any(part in {'', '.', '..'} for part in parts):
        fail('INVALID_PATH')
    return parts


def expected_hash(value, allow_null=False):
    if value is None and allow_null:
        return value
    if not isinstance(value, str) or not SHA.fullmatch(value):
        fail('INVALID_ARGUMENT')
    return value


def validate_request(operation, value):
    """Validate without filesystem access; run both in manager and helper."""
    if operation == 'read':
        exact_keys(value, ('files',), ('max_output_bytes',))
        files = value['files']
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_READ_FILES:
            fail('INVALID_ARGUMENT')
        integer(value.get('max_output_bytes', CONTENT_LIMIT), 1, CONTENT_LIMIT)
        for item in files:
            exact_keys(item, ('path',), ('start_line', 'line_count'))
            relative_path(item['path'])
            integer(item.get('start_line', 1), 1, 1000000)
            integer(item.get('line_count', 200), 1, 2000)
    elif operation == 'edit':
        exact_keys(value, ('files',))
        files = value['files']
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_EDIT_FILES:
            fail('INVALID_ARGUMENT')
        paths, content_bytes, edit_count = set(), 0, 0
        for item in files:
            exact_keys(item, ('path', 'expected_sha256', 'edits'))
            relative_path(item['path'])
            if item['path'] in paths:
                fail('INVALID_ARGUMENT')
            paths.add(item['path'])
            expected_hash(item['expected_sha256'])
            edits = item['edits']
            if not isinstance(edits, list) or not 1 <= len(edits) <= 32:
                fail('INVALID_ARGUMENT')
            for edit in edits:
                exact_keys(edit, ('old_text', 'new_text'))
                old, new = text(edit['old_text']), text(edit['new_text'])
                if not old:
                    fail('INVALID_ARGUMENT')
                content_bytes += len(old) + len(new)
                edit_count += 1
                if content_bytes > FILE_LIMIT or edit_count > MAX_EDITS:
                    fail('INPUT_TOO_LARGE')
    elif operation == 'write':
        exact_keys(value, ('path', 'content', 'expected_sha256'))
        relative_path(value['path'])
        expected_hash(value['expected_sha256'], allow_null=True)
        if len(text(value['content'])) > FILE_LIMIT:
            fail('INPUT_TOO_LARGE')
    else:
        fail('INVALID_ARGUMENT')
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, UnicodeError):
        fail('INVALID_ARGUMENT')
    if len(encoded) > REQUEST_LIMIT:
        fail('INPUT_TOO_LARGE')
    return encoded


def digest(data):
    return hashlib.sha256(data).hexdigest()


def newline_metadata(data):
    crlf = data.count(b'\r\n')
    styles = [name for name, count in (
        ('CRLF', crlf), ('LF', data.count(b'\n') - crlf), ('CR', data.count(b'\r') - crlf)
    ) if count]
    return {'newline_style': 'mixed' if len(styles) > 1 else (styles[0] if styles else 'none'),
            'has_final_newline': data.endswith((b'\r', b'\n'))}


class Workspace:
    def __init__(self, root):
        self.root = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.root)

    def parent(self, path):
        parts = relative_path(path)
        current = os.dup(self.root)
        try:
            for part in parts[:-1]:
                previous = current
                current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=previous)
                os.close(previous)
            return current, parts[-1]
        except BaseException:
            os.close(current)
            raise

    def load(self, path):
        parent, name = self.parent(path)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    fail('NOT_REGULAR_FILE')
                if before.st_size > FILE_LIMIT:
                    fail('FILE_TOO_LARGE')
                chunks, size = [], 0
                while True:
                    chunk = os.read(fd, min(65536, FILE_LIMIT + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > FILE_LIMIT:
                        fail('FILE_TOO_LARGE')
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
                ) or after.st_nlink != 1:
                    fail('CONFLICT')
                data = b''.join(chunks)
                try:
                    decoded = data.decode('utf-8', 'strict')
                except UnicodeError:
                    fail('INVALID_UTF8')
                return {'path': path, 'parent': parent, 'name': name, 'data': data,
                        'text': decoded, 'sha256': digest(data), 'stat': after}
            finally:
                os.close(fd)
        except BaseException:
            os.close(parent)
            raise

    def assert_current(self, entry):
        current = self.load(entry['path'])
        try:
            if current['sha256'] != entry['sha256'] or (current['stat'].st_dev, current['stat'].st_ino) != (
                entry['stat'].st_dev, entry['stat'].st_ino
            ):
                fail('CONFLICT')
            # Reject parent/name rebinding before the eventual replace.
            parent_stat = os.fstat(entry['parent'])
            if (parent_stat.st_dev, parent_stat.st_ino) != (
                os.fstat(current['parent']).st_dev, os.fstat(current['parent']).st_ino
            ):
                fail('CONFLICT')
        finally:
            os.close(current['parent'])

    def stage(self, parent, data, mode):
        name = '.cc-text-' + uuid.uuid4().hex
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(name, dir_fd=parent)
            raise
        return name


def io_error(error):
    if isinstance(error, FileNotFoundError):
        return TextError('NOT_FOUND')
    if isinstance(error, (IsADirectoryError, NotADirectoryError)) or getattr(error, 'errno', None) == errno.ELOOP:
        return TextError('NOT_REGULAR_FILE')
    return TextError('TEXT_IO_ERROR')


def read_files(workspace, request):
    frames = []
    for spec in request['files']:
        entry = None
        try:
            entry = workspace.load(spec['path'])
            first, count = spec.get('start_line', 1), spec.get('line_count', 200)
            selected = []
            for number, line in enumerate(io.StringIO(entry['text'], newline=''), 1):
                if number >= first + count:
                    break
                if number >= first:
                    selected.append(line)
            encoded = ''.join(selected).encode('utf-8')
            frames.append({'path': spec['path'], 'sha256': entry['sha256'], 'size_bytes': len(entry['data']),
                           'start_line': first, '_selected': encoded, **newline_metadata(entry['data'])})
        except (TextError, OSError) as error:
            error = error if isinstance(error, TextError) else io_error(error)
            frames.append({'path': spec['path'], 'error': error.detail()})
        finally:
            if entry:
                os.close(entry['parent'])
    # Water-fill a shared content budget: complete small files first and give
    # the remainder to larger files, independent of their requested order.
    left = request.get('max_output_bytes', CONTENT_LIMIT)
    quotas = [0] * len(frames)
    active = [i for i, frame in enumerate(frames) if frame.get('_selected')]
    while left and active:
        share, pending = max(1, left // len(active)), []
        for i in active:
            amount = min(len(frames[i]['_selected']) - quotas[i], share, left)
            quotas[i] += amount
            left -= amount
            if quotas[i] < len(frames[i]['_selected']):
                pending.append(i)
        active = pending
    content_bytes = 0
    for i, frame in enumerate(frames):
        if 'error' in frame:
            continue
        selected = frame.pop('_selected')
        content = selected[:quotas[i]].decode('utf-8', 'ignore')
        used = len(content.encode('utf-8'))
        content_bytes += used
        truncated = used < len(selected)
        frame.update(content=content, line_count=len(content.splitlines()), truncated=truncated,
                     whole_file=frame['start_line'] == 1 and used == frame['size_bytes'],
                     read_status=('omitted_budget' if not used else 'truncated') if truncated else 'complete')
    metadata = [{key: value for key, value in frame.items() if key != 'content'} for frame in frames]
    if len(json.dumps(metadata, ensure_ascii=False).encode()) > METADATA_LIMIT:
        fail('TEXT_OUTPUT_LIMIT')
    return {'files': frames, 'content_bytes': content_bytes}


def write_file(workspace, request):
    path, expected = request['path'], request['expected_sha256']
    entry, staged, parent = None, None, None
    try:
        if expected is None:
            parent, name = workspace.parent(path)
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                fail('ALREADY_EXISTS')
            mode = 0o600
        else:
            entry = workspace.load(path)
            parent, name = entry['parent'], entry['name']
            if expected != entry['sha256']:
                fail('CONFLICT')
            mode = stat.S_IMODE(entry['stat'].st_mode)
        content = text(request['content'])
        if entry and content == entry['data']:
            return {'path': path, 'sha256': entry['sha256'], 'size_bytes': len(content), 'created': False, 'changed': False}
        staged = workspace.stage(parent, content, mode)
        if entry:
            workspace.assert_current(entry)
            os.replace(staged, name, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            # link is atomic no-replace: a concurrent create cannot be clobbered.
            try:
                os.link(staged, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            except FileExistsError:
                fail('ALREADY_EXISTS')
        return {'path': path, 'sha256': digest(content), 'size_bytes': len(content), 'created': expected is None, 'changed': True}
    finally:
        if staged and parent is not None:
            try:
                os.unlink(staged, dir_fd=parent)
            except FileNotFoundError:
                pass
        if parent is not None:
            os.close(parent)


def edit_files(workspace, request):
    entries = []
    try:
        # Prepare every file and check every match before mutating any target.
        for spec in request['files']:
            entry = workspace.load(spec['path'])
            entries.append(entry)
            if entry['sha256'] != spec['expected_sha256']:
                fail('CONFLICT')
            updated = entry['text']
            for edit in spec['edits']:
                first = updated.find(edit['old_text'])
                if first < 0:
                    fail('MATCH_NOT_FOUND')
                # count() skips overlapping matches: 'aa' occurs at both
                # offsets 0 and 1 in 'aaa', so that edit is ambiguous too.
                if updated.find(edit['old_text'], first + 1) >= 0:
                    fail('AMBIGUOUS_MATCH')
                updated = updated.replace(edit['old_text'], edit['new_text'], 1)
            data = updated.encode('utf-8')
            if len(data) > FILE_LIMIT:
                fail('FILE_TOO_LARGE')
            entry['updated'] = data
            entry['staged'] = None
        for entry in entries:
            if entry['updated'] != entry['data']:
                entry['staged'] = workspace.stage(entry['parent'], entry['updated'], stat.S_IMODE(entry['stat'].st_mode))
        for entry in entries:
            workspace.assert_current(entry)
        try:
            for entry in entries:
                if entry['staged']:
                    os.replace(entry['staged'], entry['name'], src_dir_fd=entry['parent'], dst_dir_fd=entry['parent'])
        except OSError:
            fail('PARTIAL_WRITE')
        return {'files': [{'path': entry['path'], 'sha256': digest(entry['updated']),
                           'size_bytes': len(entry['updated']), 'changed': entry['updated'] != entry['data']} for entry in entries]}
    finally:
        for entry in entries:
            if entry.get('staged'):
                try:
                    os.unlink(entry['staged'], dir_fd=entry['parent'])
                except FileNotFoundError:
                    pass
            os.close(entry['parent'])


def operate(root, operation, request):
    validate_request(operation, request)
    workspace = None
    try:
        workspace = Workspace(root)
        return {'read': read_files, 'edit': edit_files, 'write': write_file}[operation](workspace, request)
    except OSError as error:
        raise io_error(error) from None
    finally:
        if workspace:
            workspace.close()


def main():
    """Read only a bounded manager-staged payload; never echo raw exceptions."""
    try:
        with open(sys.argv[2], 'rb') as stream:
            payload = stream.read(REQUEST_LIMIT + 1)
        if len(payload) > REQUEST_LIMIT:
            fail('INPUT_TOO_LARGE')
        value = json.loads(payload)
        exact_keys(value, ('operation', 'request'))
        result = {'ok': True, 'result': operate(sys.argv[1], value['operation'], value['request'])}
    except TextError as error:
        result = {'ok': False, 'error': error.detail()}
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        result = {'ok': False, 'error': TextError('TEXT_RUNTIME_ERROR').detail()}
    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > RESPONSE_LIMIT:
        encoded = json.dumps({'ok': False, 'error': TextError('TEXT_OUTPUT_LIMIT').detail()}).encode()
    sys.stdout.buffer.write(encoded)


if __name__ == '__main__':
    main()
