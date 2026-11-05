"""Load daemon-mounted runtime settings only inside the confined API container.

Scheduled commands must invoke this module too: docker exec does not inherit
variables loaded into PID 1. Values use raw NAME=value syntax, never shell code.
"""
import os
from pathlib import Path
import re
import sys

RUNTIME_FILE = Path('/run/secrets/api-runtime')


def load_runtime(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('expected raw NAME=value lines')
        if key in values:
            raise ValueError('duplicate runtime setting')
        values[key] = value
    return values


def main() -> None:
    try:
        values = load_runtime(RUNTIME_FILE)
    except (OSError, ValueError):
        # A parser/OS exception may contain secret input or metadata.
        raise SystemExit('Cannot load API runtime settings') from None
    os.environ.update(values)
    command = sys.argv[1:] or [sys.executable, '-m', 'release']
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    main()
