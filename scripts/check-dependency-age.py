#!/usr/bin/env python3
"""Enforce dependency cooldown relative to the checked-out commit, not wall time."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
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
        if entry['ecosystem'] not in ('npm', 'pypi'):
            raise ValueError('unsupported exception ecosystem')
        if entry['ecosystem'] == 'pypi':
            timestamp(entry['cutoff'])
    return entries


def check_python(path):
    now = commit_time()
    lines = path.read_text().splitlines()
    values = [line.removeprefix('# uv-exclude-newer:').strip()
              for line in lines if line.startswith('# uv-exclude-newer:')]
    if len(values) != 1:
        raise ValueError(f'{path}: expected exactly one uv-exclude-newer timestamp')
    cutoff = timestamp(values[0])
    if cutoff > now - DAY:
        raise ValueError(f'{path}: cutoff {cutoff} must be at least 7 days before commit {now}')
    dependencies = {}
    for line in lines:
        requirement = line.split('#', 1)[0].strip()
        if not requirement:
            continue
        # Only index requirements can obey exclude-newer. Reject options, paths,
        # direct references and VCS sources before passing any input to uv.
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9_,.-]+\])?\s*([<>=!~].*)?', requirement.split(';', 1)[0].strip())
        if not match or '@' in requirement or '://' in requirement:
            raise ValueError(f'{path}: only registry requirements are allowed: {requirement}')
        dependencies[re.sub(r'[-_.]+', '-', match[1]).lower()] = (match[3] or '').strip()
    overrides = {}
    for entry in exceptions(now):
        name = re.sub(r'[-_.]+', '-', entry['name']).lower()
        if entry['ecosystem'] != 'pypi' or name not in dependencies:
            continue
        if dependencies[name] != '==' + entry['version']:
            raise ValueError(f'{path}: Python exception requires an exact pin for {name}')
        overrides[name] = entry['cutoff']
    return overrides


def registry_metadata(name):
    # One full metadata request per unique package; cache successful metadata
    # for this commit so CI cache reuse cannot hide a changed lock or cutoff.
    cache = ROOT / '.cache/dependency-age' / subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (hashlib.sha256(('dist-v2:' + name).encode()).hexdigest() + '.json')
    if target.exists():
        return json.loads(target.read_text())
    url = 'https://registry.npmjs.org/' + urllib.parse.quote(name, safe='')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                metadata = json.load(response)
            target.write_text(json.dumps(metadata))
            return metadata
        except urllib.error.URLError as error:
            if isinstance(error, urllib.error.HTTPError) and error.code != 429 and error.code < 500:
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def npm_changed(base):
    if not base or set(base) == {'0'}:
        return True
    paths = subprocess.check_output(['git', 'diff', '--name-only', base, 'HEAD', '--'], cwd=ROOT, text=True).splitlines()
    return any(Path(path).name == 'package-lock.json' or path == 'dependency-age-exceptions.json' for path in paths)


def check_npm():
    now = commit_time()
    allowed = {(e['ecosystem'], e['name'], e['version']) for e in exceptions(now)}
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
            packages.setdefault(name, []).append((version, package.get('resolved'), package.get('integrity')))
    failures = []
    def check(item):
        name, versions = item
        metadata = registry_metadata(name)
        for version, resolved, integrity in versions:
            dist = metadata['versions'][version]['dist']
            if not resolved or not integrity or resolved != dist['tarball'] or integrity != dist['integrity']:
                raise ValueError(f'{name}@{version}: resolved/integrity does not match registry artifact')
            published = timestamp(metadata['time'][version])  # missing metadata fails closed
            if published > now - DAY and ('npm', name, version) not in allowed:
                failures.append(f'{name}@{version}: published {published}, commit {now}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(check, packages.items()))
    if failures:
        raise ValueError('npm releases younger than 7 days:\n' + '\n'.join(sorted(failures)))
    count = sum(len({version for version, _, _ in entries}) for entries in packages.values())
    print(f'Cooldown passed: {count} npm versions across {len(locks)} locks')


if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--if-changed':
            if npm_changed(sys.argv[2]):
                check_npm()
            else:
                print('npm cooldown skipped: lockfiles and exceptions unchanged')
        elif len(sys.argv) == 2:
            print(json.dumps(check_python(Path(sys.argv[1]).resolve())))
        else:
            check_npm()
    except (ValueError, KeyError, OSError) as error:
        sys.exit(str(error))
