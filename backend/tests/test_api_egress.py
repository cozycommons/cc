"""Source drift tripwire; the sidecar/network enforce policy at runtime."""
import ast
import importlib.util
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / 'deploy/api-egress'
SPEC = importlib.util.spec_from_file_location('egress_start', DEPLOY / 'start.py')
start = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(start)

# These are response links, request Origin/Referer headers, sandbox constants, or
# offline commands main:app never imports (bikes.ingest), not API destinations. Scope exemptions to the file so a new caller needs review.
NON_EGRESS = {
    'cozycommons.dev': {'bikes/routes.py', 'partiful/agent_tools.py', 'resy/agent_tools.py', 'espn/agent_tools.py',
                       'ig_logger/sinks/beli/agent_tools.py', 'trips/agent_tools.py',
                       'floor_planner/agent_tools.py', 'cc_mcp/commons_tools.py'},
    'github.com': {'partiful/agent_tools.py', 'resy/agent_tools.py', 'espn/agent_tools.py',
                   'ig_logger/sinks/beli/agent_tools.py'},
    'partiful.com': {'partiful/partiful_client.py'},
    'resy.com': {'resy/resy_client.py'},
    'fantasy.espn.com': {'espn/team_claims.py'},
    'venmo.com': {'venmo/links.py'},
    'localhost': {'main.py', 'dice/notifications.py'},
    '127.0.0.1': {'main.py', 'runtime_policy.py', 'trips/local.py'},
    's3.amazonaws.com': {'bikes/ingest.py'},
    'download.bbbike.org': {'bikes/basemap.py'},
    # bikes.model's weather history download runs offline; the API imports the module for constants only.
    'archive-api.open-meteo.com': {'bikes/model.py'},
    'api.cozycommons.dev': {'bikes/routes.py'},
}


def literal_hosts(source):
    tree = ast.parse(source)
    # Documentation URLs do not become runtime strings.
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    return {m.group(1).lower() for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
            for m in re.finditer(r'https?://([a-zA-Z0-9][a-zA-Z0-9.-]*)', node.value)}


def test_api_literal_hosts_are_inventoried():
    allowed = {s for s in (DEPLOY / 'hosts.txt').read_text().splitlines() if s and not s.startswith('#')}
    unknown = []
    for path in (ROOT / 'backend').rglob('*.py'):
        rel = path.relative_to(ROOT / 'backend')
        if any(p in {'tests', '.venv', '__pycache__', 'crowdset', 'compute'} for p in rel.parts):
            continue  # Crowdset and compute are distinct runtimes, not main:app.
        for host in literal_hosts(path.read_text()):
            if host not in allowed and str(rel) not in NON_EGRESS.get(host, set()):
                unknown.append(f'{rel}: {host}')
    assert not unknown, 'Uninventoried API hosts (review hosts.txt and docs/api-egress.md): ' + ', '.join(unknown)


def test_tripwire_sees_new_host_and_fstring():
    assert literal_hosts('url = f"https://new.example.test/{path}"') == {'new.example.test'}


@pytest.mark.parametrize('value', ['.supabase.co', '*.run.app', '127.0.0.1', 'host\nhttp_access allow all', 'EXAMPLE.com', 'a;id'])
def test_configuration_rejects_non_hostnames(value):
    with pytest.raises(ValueError):
        start.hostname(value)


def test_policy_fails_closed_and_checks_host_before_dns():
    config = start.squid_config('enforce', 'synthetic.supabase.co')
    assert config.index('http_access deny !approved') < config.index('http_access deny private')
    assert 'ssl_bump splice tls_approved\nssl_bump terminate all' in config
    assert 'dstdomain -n' in config
    with pytest.raises(ValueError):
        start.squid_config('typo', 'synthetic.supabase.co')
    audit = start.squid_config('audit', 'synthetic.supabase.co')
    assert 'http_access deny !approved' not in audit
    assert 'mode=audit' in audit


def test_offline_rollout_preflight():
    spec = importlib.util.spec_from_file_location('egress_preflight', ROOT / 'scripts/check-api-egress-config.py')
    preflight = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preflight)
    values = {
        'SUPABASE_URL': 'https://synthetic.supabase.co',
        'EXPECTED_SUPABASE_PROJECT': 'synthetic',
        'SUPABASE_SERVICE_KEY': 'synthetic-only',
        'SUPABASE_DB_URL': 'postgresql://postgres.synthetic:synthetic@synthetic.pooler.supabase.com:5432/postgres?sslmode=require',
    }
    preflight.check(values, 'synthetic.supabase.co', 'synthetic.pooler.supabase.com')
    for override in [
        {'SUPABASE_URL': 'https://other.supabase.co'},
        {'ANALYTICS_DATABASE_URL': 'postgresql://reader:synthetic@other.pooler.supabase.com:5432/postgres'},
        {'SUPABASE_DB_URL': values['SUPABASE_DB_URL'].replace('sslmode=require', 'sslmode=disable')},
        {'SUPABASE_DB_URL': values['SUPABASE_DB_URL'].split('?')[0]},
        {'SUPABASE_DB_URL': values['SUPABASE_DB_URL'].replace('synthetic.pooler.supabase.com', 'db.synthetic.supabase.co')},
        {'SUPABASE_DB_URL': values['SUPABASE_DB_URL'] + '&hostaddr=1.1.1.1'},
    ]:
        with pytest.raises(ValueError):
            preflight.check(values | override, 'synthetic.supabase.co', 'synthetic.pooler.supabase.com')
