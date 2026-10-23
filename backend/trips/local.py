"""Run the normal Commons application against the owned loopback Trips sandbox."""
import os

if os.getenv('COZY_TRIPS_LOCAL') != '1' or os.getenv('SUPABASE_URL') != 'http://127.0.0.1:55321':
    raise RuntimeError('The Trips local entry point requires its dedicated loopback Supabase instance.')

# main suppresses dotenv loading and external side effects under this local policy.
from main import app  # noqa: E402,F401
