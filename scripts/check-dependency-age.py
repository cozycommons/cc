#!/usr/bin/env python3
"""Enforce dependency cooldown relative to the checked-out commit, not wall time."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.timedelta(days=7)


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps must include a timezone')
    return parsed


def commit_time():
    return dt.datetime.fromtimestamp(int(subprocess.check_output(
        ['git', 'log', '-1', '--format=%ct'], cwd=ROOT)), dt.timezone.utc)


def exceptions(now):
    entries = json.loads((ROOT / 'dependency-age-exceptions.json').read_text())
    for entry in entries:
        if not all(entry.get(k) for k in ('ecosystem', 'name', 'version', 'reason', 'reviewed_by', 'reviewed_on', 'expires')):
            raise ValueError('incomplete dependency age exception')
        reviewed = dt.date.fromisoformat(entry['reviewed_on'])
        expires = dt.date.fromisoformat(entry['expires'])
        if not reviewed <= now.date() <= expires or expires - reviewed > dt.timedelta(days=30):
            raise ValueError(f'invalid or expired exception: {entry}')
    return {(e['ecosystem'], e['name'], e['version']) for e in entries}


def check_python(path):
    now = commit_time()
    lines = path.read_text().splitlines()
    values = [line.removeprefix('# uv-exclude-newer:').strip()
              for line in lines if line.startswith('# uv-exclude-newer:')]
    if len(values) != 1:
        raise ValueError(f'{path}: expected exactly one uv-exclude-newer timestamp')
    cutoff = timestamp(values[0])
    if cutoff > now - DAY and ('pypi-lock', str(path.relative_to(ROOT)), values[0]) not in exceptions(now):
        raise ValueError(f'{path}: cutoff {cutoff} must be at least 7 days before commit {now}')


def registry_times(name):
    # One abbreviated metadata request per unique package; cache successful metadata
    # for this commit so CI cache reuse cannot hide a changed lock or cutoff.
    cache = ROOT / '.cache/dependency-age' / subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (hashlib.sha256(name.encode()).hexdigest() + '.json')
    if target.exists():
        return json.loads(target.read_text())
    url = 'https://registry.npmjs.org/' + urllib.parse.quote(name, safe='')
    with urllib.request.urlopen(url, timeout=20) as response:
        times = json.load(response)['time']
    target.write_text(json.dumps(times))
    return times


def check_npm():
    now = commit_time()
    allowed = exceptions(now)
    packages = {}
    locks = subprocess.check_output(['git', 'ls-files', '*package-lock.json', 'package-lock.json'], cwd=ROOT, text=True).splitlines()
    for lock in locks:
        data = json.loads((ROOT / lock).read_text())
        if data.get('lockfileVersion') not in (2, 3):
            raise ValueError(f'{lock}: unsupported lockfile format')
        for path, package in data['packages'].items():
            if not path or package.get('link'):
                continue
            name = package.get('name') or path.rsplit('node_modules/', 1)[-1]
            version = package['version']
            resolved = package.get('resolved', '')
            if resolved and not resolved.startswith('https://registry.npmjs.org/'):
                raise ValueError(f'{lock}: {name}@{version} is not a registry release')
            packages.setdefault(name, set()).add(version)
    failures = []
    def check(item):
        name, versions = item
        times = registry_times(name)
        for version in versions:
            published = timestamp(times[version])  # missing metadata fails closed
            if published > now - DAY and ('npm', name, version) not in allowed:
                failures.append(f'{name}@{version}: published {published}, commit {now}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(check, packages.items()))
    if failures:
        raise ValueError('npm releases younger than 7 days:\n' + '\n'.join(sorted(failures)))
    print(f'Cooldown passed: {sum(map(len, packages.values()))} npm versions across {len(locks)} locks')


if __name__ == '__main__':
    try:
        if len(sys.argv) == 2:
            check_python(Path(sys.argv[1]).resolve())
        else:
            check_npm()
    except (ValueError, KeyError, OSError) as error:
        sys.exit(str(error))
