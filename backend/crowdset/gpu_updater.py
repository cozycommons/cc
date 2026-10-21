"""Pull CI-approved worker releases from main; quiesce, install and roll back."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPOSITORY = 'cozycommons/cc'
REQUIRED = {'frontend', 'backend', 'crowdset-container', 'crowdset (ubuntu-latest)', 'crowdset (macos-latest)'}
FILES = {
    'gpu_worker.py': 'backend/crowdset/gpu_worker.py',
    'crowdset-gpu-worker.service': 'scripts/systemd/crowdset-gpu-worker.service',
    'crowdset-gpu-update.service': 'scripts/systemd/crowdset-gpu-update.service',
    'crowdset-gpu-update.timer': 'scripts/systemd/crowdset-gpu-update.timer',
    'gpu_updater.py': 'backend/crowdset/gpu_updater.py',
}
# Processing modules travel with the same CI-approved release as the renderer.
for module in ('audio', 'video', 'progress', 'limits', 'config', 'storage', 'blobs', 'r2',
               'worker', 'composition', 'previews', 'timestamps', 'gpu_worker', 'remote_agent', 'youtube'):
    FILES['crowdset/' + module + '.py'] = 'backend/crowdset/' + module + '.py'

SERVICE = 'crowdset-gpu-worker.service'


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.new')
    with temporary.open('wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def record(path, value):
    atomic(path, json.dumps(value, allow_nan=False).encode())


def get(url):
    request = Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'crowdset-gpu-updater'})
    with urlopen(request, timeout=20) as response:
        content = response.read(2 * 1024 ** 2 + 1)
    if len(content) > 2 * 1024 ** 2:
        raise ValueError('Release response exceeds its bound')
    return content


def approved(payload, sha):
    if payload.get('total_count', 0) > 100:
        return False
    latest = {}
    for check in payload.get('check_runs', []):
        if check.get('app', {}).get('slug') != 'github-actions' or check.get('head_sha') != sha:
            continue
        if check['id'] > latest.get(check['name'], {}).get('id', -1):
            latest[check['name']] = check
    return REQUIRED <= latest.keys() and all(c['status'] == 'completed' and c['conclusion'] == 'success' for c in latest.values())


def control(*args):
    return subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, check=True, timeout=30).stdout.strip()


def destination(root, name):
    return root / name if name.endswith('.py') else Path.home() / '.config/systemd/user' / name


def bundle_hash(folder):
    return {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in FILES}


def validate(folder):
    with tempfile.TemporaryDirectory() as temporary:
        for name in FILES:
            content = (folder / name).read_bytes()
            if not content or len(content) > 1024 ** 2:
                raise ValueError('Release contains an empty or oversized file')
            if name.endswith('.py'):
                compiled = Path(temporary) / (name + 'c')
                compiled.parent.mkdir(parents=True, exist_ok=True)
                py_compile.compile(str(folder / name), cfile=str(compiled), doraise=True)
                if '/' not in name:
                    subprocess.run(['/usr/bin/python3', str(folder / name), '--help'], capture_output=True, check=True, timeout=10)
    subprocess.run(['systemd-analyze', '--user', 'verify', *[str(folder / n) for n in FILES if not n.endswith('.py')]],
                   capture_output=True, check=True, timeout=20)


def running_pid():
    return int(control('show', SERVICE, '--property=MainPID', '--value'))


def wait_paused(root, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pid = running_pid()
        if not pid:
            return True
        try:
            status = json.loads((root / 'data/status.json').read_text())
            if status.get('pid') == pid and status.get('state') == 'paused' and time.time() - status['updated_at'] < 10:
                return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.5)
    return False


def healthy(root, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            status = json.loads((root / 'data/status.json').read_text())
            if status.get('pid') == running_pid() and status.get('state') in ('idle', 'rendering', 'offline') and time.time() - status['updated_at'] < 10:
                return True
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
        time.sleep(0.5)
    return False


def install_files(root, folder):
    for name in FILES:
        path = destination(root, name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic(path, (folder / name).read_bytes())


def rollback(root, pending):
    control('stop', SERVICE)
    install_files(root, root / 'rollback')
    control('daemon-reload')
    (root / 'data/update-requested').unlink(missing_ok=True)
    control('start', SERVICE)
    if not healthy(root):
        raise RuntimeError('Rollback failed health verification; retained backup needs attention')
    record(root / 'update-status.json', {'state': 'rolled_back', 'failed_sha': pending['sha'], 'updated_at': time.time()})
    (root / 'pending-update.json').unlink()


def deploy(root, pending):
    for name in FILES:
        path = destination(root, name)
        if not path.exists():
            if not name.startswith('crowdset/'):
                raise RuntimeError('Worker installation is incomplete; service has not been stopped')
            atomic(path, (root / 'incoming' / name).read_bytes())
    pause = root / 'data/update-requested'
    pause.touch(mode=0o600)
    if not wait_paused(root):
        record(root / 'update-status.json', {'state': 'waiting_for_render', 'sha': pending['sha'], 'updated_at': time.time()})
        return
    control('stop', SERVICE)
    # A manually launched worker must not be interrupted or share a release install.
    with (root / 'data/worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backup = root / 'rollback'
        backup.mkdir(mode=0o700, exist_ok=True)
        for name in FILES:
            atomic(backup / name, destination(root, name).read_bytes())
        pending['phase'] = 'installing'
        record(root / 'pending-update.json', pending)
        try:
            install_files(root, root / 'incoming')
            control('daemon-reload')
        except Exception:
            fcntl.flock(lock, fcntl.LOCK_UN)
            rollback(root, pending)
            raise
    try:
        pause.unlink(missing_ok=True)
        control('start', SERVICE)
        if not healthy(root):
            raise RuntimeError('New worker failed its startup health check')
        record(root / 'deployment.json', {'sha': pending['sha'], 'files': bundle_hash(root / 'incoming'), 'updated_at': time.time()})
        (root / 'pending-update.json').unlink()
        record(root / 'update-status.json', {'state': 'current', 'sha': pending['sha'], 'updated_at': time.time()})
    except Exception:
        rollback(root, pending)
        raise


def update(root):
    pending_path = root / 'pending-update.json'
    if pending_path.exists():
        pending = json.loads(pending_path.read_text())
        if pending.get('phase') == 'installing':
            rollback(root, pending)
        else:
            deploy(root, pending)
        return
    sha = json.loads(get(f'https://api.github.com/repos/{REPOSITORY}/commits/main'))['sha']
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise ValueError('Invalid main commit')
    installed = json.loads((root / 'deployment.json').read_text()) if (root / 'deployment.json').exists() else {}
    status = json.loads((root / 'update-status.json').read_text()) if (root / 'update-status.json').exists() else {}
    complete_bundle = FILES.keys() <= installed.get('files', {}).keys() and all(destination(root, name).is_file() for name in FILES)
    if (installed.get('sha') == sha and complete_bundle) or status.get('failed_sha') == sha:
        return
    checks = json.loads(get(f'https://api.github.com/repos/{REPOSITORY}/commits/{sha}/check-runs?per_page=100'))
    if not approved(checks, sha):
        record(root / 'update-status.json', {'state': 'waiting_for_ci', 'sha': sha, 'updated_at': time.time()})
        return
    incoming = root / 'incoming'
    incoming.mkdir(mode=0o700, exist_ok=True)
    try:
        for name, path in FILES.items():
            atomic(incoming / name, get(f'https://raw.githubusercontent.com/{REPOSITORY}/{sha}/{path}'))
    except HTTPError as exc:
        if exc.code != 404:
            raise
        record(root / 'update-status.json', {'state': 'waiting_for_release', 'sha': sha, 'updated_at': time.time()})
        return
    validate(incoming)
    if all(destination(root, name).exists() and hashlib.sha256(destination(root, name).read_bytes()).hexdigest() == digest
           for name, digest in bundle_hash(incoming).items()):
        record(root / 'deployment.json', {'sha': sha, 'files': bundle_hash(incoming), 'updated_at': time.time()})
        record(root / 'update-status.json', {'state': 'current', 'sha': sha, 'updated_at': time.time()})
        return
    pending = {'sha': sha, 'phase': 'staged'}
    record(pending_path, pending)
    deploy(root, pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    root = parser.parse_args().root.resolve()
    os.umask(0o077)
    with (root / 'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            update(root)
        except Exception as exc:
            print(f'Worker update deferred or failed: {type(exc).__name__}: {exc}', flush=True)
            raise


if __name__ == '__main__':
    main()
