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
from urllib.parse import urlparse

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
    database = urlparse(result.get('DB_URL', ''))
    if database.scheme != 'postgresql' or database.hostname != '127.0.0.1' or database.port != 55322 or database.path != '/postgres':
        raise RuntimeError('Trips migrations require the dedicated loopback database on port 55322.')
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
        'studio,meta,imgproxy,inbucket,realtime,edge-runtime,analytics,vector', capture=True)
    print('Dedicated Trips Supabase started (loopback ports 55321 and 55322).')


def migrate_and_seed(settings):
    env = dict(os.environ, SUPABASE_DB_URL=settings['DB_URL'])
    subprocess.run([sys.executable, str(ROOT / 'backend/migration_runner.py'), '--family', 'all'],
                   env=env, check=True)
    subprocess.run(['psql', settings['DB_URL'], '-X', '-v', 'ON_ERROR_STOP=1',
                    '--single-transaction', '--file', str(ROOT / 'supabase/dice-local-table-grants.sql')],
                   check=True, stdout=subprocess.DEVNULL)
    from supabase import create_client
    admin = create_client(settings['API_URL'], settings['SERVICE_ROLE_KEY'])
    users = admin.auth.admin.list_users()
    for name in ['Matt', 'Alex', 'Jamie']:
        email = f'{name.lower()}@trips.local'
        if not any(user.email == email for user in users):
            admin.auth.admin.create_user({'email': email, 'password': 'local-trips-password',
                                          'email_confirm': True, 'user_metadata': {'full_name': name}})
    # Explicit sandbox seed only: opening Trips never creates a Dice profile.
    matt = next(user for user in admin.auth.admin.list_users() if user.email == 'matt@trips.local')
    if not admin.table('dice_profiles').select('user_id').eq('user_id', matt.id).execute().data:
        admin.table('dice_profiles').insert({'user_id': matt.id, 'display_name': 'Matt'}).execute()


def run(settings, built=False):
    for port in [8011, 8815]:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is in use. Refusing to replace another service.')
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'USER', 'LOGNAME', 'VIRTUAL_ENV'}}
    env.update(COZY_TRIPS_LOCAL='1', SUPABASE_URL=settings['API_URL'],
               SUPABASE_SERVICE_KEY=settings['SERVICE_ROLE_KEY'], VITE_API_URL='/api',
               VITE_SUPABASE_URL='dice-sandbox:same-origin',
               VITE_DICE_LOCAL_HARNESS='false',
               VITE_SUPABASE_ANON_KEY=settings.get('PUBLISHABLE_KEY') or settings['ANON_KEY'])
    if built:
        # Normal production bundle, local data: no synthetic login controls.
        subprocess.run(['npm', 'run', 'build:check'], cwd=ROOT / 'frontend', env=env, check=True)
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
        frontend = (['npm', 'exec', 'vite', '--', 'preview', '--mode', 'development',
                     '--config', 'vite.trips.config.js', '--host', '127.0.0.1', '--port', '8815', '--strictPort']
                    if built else ['npm', 'run', 'dev', '--', '--config', 'vite.trips.config.js'])
        children.append(subprocess.Popen(frontend,
                                         cwd=ROOT / 'frontend', env=env))
        print('Cozy Trips: http://localhost:8815/trips (local data; '
              + ('production bundle)' if built else 'synthetic login controls)'), flush=True)
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
    parser.add_argument('--built', action='store_true', help='Run the normal production bundle against local data.')
    arguments = parser.parse_args()
    if arguments.built and arguments.command != 'run':
        parser.error('--built is only supported with run')
    if arguments.command == 'setup':
        prepare()
    settings = local_settings()
    if arguments.command in ['setup', 'seed']:
        migrate_and_seed(settings)
    else:
        run(settings, built=arguments.built)
