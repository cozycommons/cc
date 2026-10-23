#!/usr/bin/env python3
"""Dedicated local Trips runtime. Run with backend/.venv/bin/python."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.trips-dev'
CLI = ROOT / 'node_modules/.bin/supabase'


def cli(*arguments, capture=False):
    return subprocess.run([str(CLI), '--workdir', str(WORK), *arguments],
                          check=True, text=True, capture_output=capture)


def local_settings():
    result = json.loads(cli('status', '-o', 'json', capture=True).stdout)
    if result.get('API_URL') != 'http://127.0.0.1:55321':
        raise RuntimeError('Refusing to use any other Supabase instance.')
    containers = json.loads(subprocess.check_output([
        'docker', 'inspect', 'supabase_kong_cozy-trips-local', 'supabase_db_cozy-trips-local'], text=True))
    for container in containers:
        for bindings in container['NetworkSettings']['Ports'].values():
            if any(binding['HostIp'] != '127.0.0.1' for binding in bindings or []):
                raise RuntimeError('Trips Supabase must publish ports only on loopback.')
    return result


def prepare():
    (WORK / 'supabase').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'supabase/trips-local.toml', WORK / 'supabase/config.toml')
    network = subprocess.run(['docker', 'network', 'inspect', 'cozy-trips-local'],
                             capture_output=True, text=True)
    if network.returncode:
        subprocess.run(['docker', 'network', 'create', '--driver', 'bridge', '--opt',
                        'com.docker.network.bridge.host_binding_ipv4=127.0.0.1',
                        'cozy-trips-local'], check=True, stdout=subprocess.DEVNULL)
    elif json.loads(network.stdout)[0]['Options'].get('com.docker.network.bridge.host_binding_ipv4') != '127.0.0.1':
        raise RuntimeError('Existing Trips Docker network is not bound to loopback.')
    cli('--network-id', 'cozy-trips-local', 'start', '--exclude',
        'studio,meta,imgproxy,inbucket,realtime,storage,edge-runtime,analytics,vector', capture=True)
    print('Dedicated Trips Supabase started (loopback ports 55321 and 55322).')


def migrate_and_seed(settings):
    env = dict(os.environ, SUPABASE_DB_URL=settings['DB_URL'])
    subprocess.run([sys.executable, str(ROOT / 'backend/migration_runner.py'), '--family', 'trips'],
                   env=env, check=True)
    from supabase import create_client
    admin = create_client(settings['API_URL'], settings['SERVICE_ROLE_KEY'])
    users = admin.auth.admin.list_users()
    for name in ['Matt', 'Alex', 'Jamie']:
        email = f'{name.lower()}@trips.local'
        if not any(user.email == email for user in users):
            admin.auth.admin.create_user({'email': email, 'password': 'local-trips-password',
                                          'email_confirm': True, 'user_metadata': {'full_name': name}})


def run(settings):
    for port in [8011, 8815]:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is in use. Refusing to replace another service.')
    env = dict(os.environ, COZY_TRIPS_LOCAL='1', SUPABASE_URL=settings['API_URL'],
               SUPABASE_SERVICE_KEY=settings['SERVICE_ROLE_KEY'], VITE_API_URL='/api',
               VITE_SUPABASE_URL='dice-sandbox:same-origin',
               VITE_SUPABASE_ANON_KEY=settings.get('PUBLISHABLE_KEY') or settings['ANON_KEY'])
    children = []
    def stop(*_):
        for child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'trips.local:app',
                                          '--host', '127.0.0.1', '--port', '8011', '--no-proxy-headers'],
                                         cwd=ROOT / 'backend', env=env))
        children.append(subprocess.Popen(['npm', 'run', 'dev', '--', '--config', 'vite.trips.config.js'],
                                         cwd=ROOT / 'frontend', env=env))
        print('Cozy Trips: http://localhost:8815/trips (local synthetic accounts)', flush=True)
        while all(child.poll() is None for child in children):
            try:
                children[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    finally:
        stop()
        for child in children:
            child.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'run', 'seed'])
    arguments = parser.parse_args()
    if arguments.command == 'setup':
        prepare()
    settings = local_settings()
    if arguments.command in ['setup', 'seed']:
        migrate_and_seed(settings)
    else:
        run(settings)
