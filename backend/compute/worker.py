"""Poll shared jobs and execute installed declarations in bounded subprocesses."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading

from .client import Client
from .jobs import Registry, Resources
from .runner import serve, write_status
from .process import run as run_process


HEARTBEAT_SECONDS = 15


class Source:
    def __init__(self, root, client, modules, capacity, worker=None):
        self.root, self.client, self.modules, self.capacity = Path(root), client, modules, capacity
        self.registry = Registry.load(modules)
        self.worker = worker or socket.gethostname()

    def claim(self):
        return self.client.call('worker/claim', {'worker': self.worker, 'types': list(self.registry.jobs),
                                                'capacity': self.capacity.model_dump()})

    def run(self, job):
        directory = self.root / 'jobs' / job['id'] / job['claim']
        directory.mkdir(parents=True, mode=0o700)
        identity = {'job': job['id'], 'claim': job['claim']}
        try:
            spec = self.registry.get(job['type'])
            if not Resources(**job['resources']).fits(self.capacity) or not spec.resources.fits(self.capacity):
                raise ValueError('Job exceeds worker capacity')
            (directory / 'request.json').write_text(json.dumps({
                'modules': self.modules, 'type': job['type'], 'payload': job['payload']}))
            # Handlers run as trusted code, but do not inherit control-plane tokens.
            env = {key: value for key, value in os.environ.items()
                   if key not in ('CC_COMPUTE_WORKER_TOKEN', 'CC_COMPUTE_PROJECT_TOKENS', 'CROWDSET_WORKER_TOKEN')}
            with (directory / 'worker.log').open('wb') as log:
                def heartbeat():
                    write_status(self.root, 'rendering', job['id'])
                    self.client.call('worker/heartbeat', {**identity, 'progress': {'stage': 'running'}})
                run_process([sys.executable, '-m', 'compute.execute', str(directory)], log,
                            min(spec.timeout_seconds, job['timeout_seconds']), heartbeat,
                            env=env, interval=HEARTBEAT_SECONDS)
            result = json.loads((directory / 'result.json').read_text())
            self.client.call('worker/finish', {**identity, 'result': result})
        except Exception as exc:
            try:
                self.client.call('worker/finish', {**identity, 'error': str(exc)[:1000]})
            except Exception:
                pass  # Expiry recovers the job if the server cannot be reached.


def configured_source(root, capacity=None):
    return Source(root, Client(os.environ['CC_COMPUTE_URL'], os.environ['CC_COMPUTE_WORKER_TOKEN']),
                  os.environ['CC_JOB_MODULES'].split(','), capacity or Resources.environment())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    serve(args.root.resolve(), [configured_source(args.root.resolve())], stop)


if __name__ == '__main__':
    main()
