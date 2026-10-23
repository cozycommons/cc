import os
from pathlib import Path
import subprocess
import sys

import pytest

from runtime_policy import initialize_runtime_policy, TRIPS_LOCAL_SUPABASE_URL


def test_shared_trips_runtime_keeps_local_capability_guards():
    loaded = []
    policy = initialize_runtime_policy({'COZY_TRIPS_LOCAL': '1', 'ENABLE_SCHEDULER': 'true'}, lambda: loaded.append(True))
    assert loaded == []
    assert policy.is_trips_sandbox and not policy.is_dice_sandbox
    assert not policy.scheduler_enabled and not policy.allow_cache_warmup and not policy.allow_external_side_effects
    policy.require_safe_supabase_url(TRIPS_LOCAL_SUPABASE_URL)
    for url in ['https://example.supabase.co', 'http://127.0.0.1:54321', 'http://localhost:55321', None]:
        with pytest.raises(RuntimeError, match='COZY_TRIPS_LOCAL requires'):
            policy.require_safe_supabase_url(url)
    with pytest.raises(RuntimeError, match='Choose one local harness'):
        initialize_runtime_policy({'COZY_TRIPS_LOCAL': '1', 'DICE_LOCAL_HARNESS': 'true'}, lambda: None)


def test_shared_local_app_ignores_dotenv_and_includes_normal_routes(tmp_path):
    (tmp_path / '.env.local').write_text('SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_KEY=must-not-load\n')
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'PYTHONPATH': str(backend), 'COZY_TRIPS_LOCAL': '1',
           'SUPABASE_URL': TRIPS_LOCAL_SUPABASE_URL, 'SUPABASE_SERVICE_KEY': 'local-test-key'}
    env.pop('DICE_LOCAL_HARNESS', None)
    result = subprocess.run([sys.executable, '-c',
        "import main; from trips.local import app; assert app is main.app; "
        "assert main.SUPABASE_URL == 'http://127.0.0.1:55321'; "
        "paths={r.path for r in app.routes}; assert {'/trips/me','/dice/me','/commons/scene','/ready'} <= paths, paths"],
        cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
