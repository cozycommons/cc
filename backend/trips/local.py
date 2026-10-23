"""Local-only composition for Cozy Trips; production uses main.py's shared app."""
import os

from fastapi import FastAPI
from supabase import create_client

from .routes import router

if os.getenv('COZY_TRIPS_LOCAL') != '1' or os.getenv('SUPABASE_URL') != 'http://127.0.0.1:55321':
    raise RuntimeError('The Trips local entry point requires its dedicated loopback Supabase instance.')

app = FastAPI(title='Cozy Trips local API')
app.state.trips_supabase = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
app.include_router(router, prefix='/trips')


@app.get('/health')
def health():
    app.state.trips_supabase.table('trips_groups').select('id').limit(1).execute()
    return {'status': 'ok', 'project': 'cozy-trips-local'}
