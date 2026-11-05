"""422 bodies never echo submitted values: passwords, cookies or SMS codes."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import request_validation
from commons_account import routes

SECRET = 'SYNTHETIC-SECRET-VALUE'


@pytest.fixture
def client():
    app = FastAPI()
    request_validation.install(app)
    app.state.mcp_supabase = SimpleNamespace(auth=SimpleNamespace(
        get_user=lambda _: SimpleNamespace(user=SimpleNamespace(id='u1', email='sam@example.test'))))
    app.include_router(routes.router, prefix='/account')
    return TestClient(app)


AUTH = {'Authorization': 'Bearer session'}


@pytest.mark.parametrize('body', [
    {'password': SECRET},                                   # missing field: the default echoes the whole body
    {'login': 'sam@example.test', 'password': [SECRET]},    # wrong type
    {'login': 'sam@example.test', 'password': SECRET, 'extra': SECRET},  # forbidden extra field
    {'login': SECRET + 'K', 'password': SECRET},       # pattern failure
])
def test_validation_errors_name_the_field_but_never_the_value(client, body):
    response = client.post('/account/linked-accounts/beli', headers=AUTH, json=body)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert all(set(error) <= {'type', 'loc', 'msg'} for error in response.json()['detail'])


def test_malformed_json_is_not_echoed(client):
    response = client.post('/account/linked-accounts/beli', headers={**AUTH, 'Content-Type': 'application/json'},
                           content='{"password": "' + SECRET + '"')
    assert response.status_code == 422 and SECRET not in response.text


def test_the_app_installs_the_handler():
    source = (Path(__file__).resolve().parents[1] / 'main.py').read_text()
    assert 'request_validation.install(app)' in source
