"""Subprocess boundary for one installed, registered handler."""
import json
from pathlib import Path
import sys

from .jobs import Registry
from .queue import encode


def main():
    directory = Path(sys.argv[1])
    request = json.loads((directory / 'request.json').read_text())
    job = Registry.load(request['modules']).get(request['type'])
    value = job.input.model_validate(request['payload'])
    result = job.handler(value, directory)
    result = job.output.model_validate(result).model_dump(mode='json')
    (directory / 'result.json').write_text(encode(result))


if __name__ == '__main__':
    main()
