from uuid import uuid4

import pytest
from postgrest.exceptions import APIError
from supabase import create_client

from floor_planner.scans import BUCKET, cleanup_pending, router
from tests.test_floor_planner_integration import create_account, local_floor_planner_api  # noqa: F401
from tests.test_floor_planner_scans import synthetic_scan


def test_private_scan_storage_collaborators_conflicts_and_revocation(local_floor_planner_api):
    api, service, settings, accounts, documents = local_floor_planner_api
    api.app.include_router(router, prefix='/floor-planner')
    suffix = uuid4().hex
    owner, owner_client = create_account(service, settings, accounts, f'scan-owner-{suffix}@floor-planner.local')
    recipient_email = f'scan-editor-{suffix}@floor-planner.local'
    recipient, recipient_client = create_account(service, settings, accounts, recipient_email)
    outsider, outsider_client = create_account(service, settings, accounts, f'scan-outside-{suffix}@floor-planner.local')
    anonymous_client = create_client(settings['API_URL'], settings['ANON_KEY'])
    scene = {'version': 2, 'units': 'inches', 'elements': [], 'viewport': None}
    plan = api.post('/floor-planner/plans', headers=owner, json={'title': 'Synthetic scan QA', 'template': 'blank', 'scene': scene}).json()
    documents.append(plan['id'])
    endpoint = f'/floor-planner/plans/{plan["id"]}/scan'
    invite = api.post(f'/floor-planner/plans/{plan["id"]}/invitations', headers=owner, json={'email': recipient_email}).json()
    assert api.get(endpoint, headers=owner).json() == {'scan': None}
    assert service.rpc('floor_planner_release_readiness', {}).execute().data is True
    content = synthetic_scan()
    first = api.put(endpoint + '?filename=synthetic.usdz', headers=owner, content=content)
    assert first.status_code == 200, first.text
    scan = first.json()['scan']
    assert scan['byte_size'] == len(content) and 'object_key' not in scan
    assert api.get(endpoint + '/content', headers=recipient).content == content
    assert api.get(endpoint + '/content', headers=owner).headers['cache-control'] == 'private, no-store'
    for headers in ({}, outsider):
        assert api.get(endpoint, headers=headers).status_code in {401, 404}
        assert api.get(endpoint + '/content', headers=headers).status_code in {401, 404}
        assert api.put(endpoint, headers=headers, content=content).status_code in {401, 404}
    for browser in (owner_client, recipient_client, outsider_client, anonymous_client):
        with pytest.raises(APIError):
            browser.table('floor_plan_scans').select('*').execute()
    stored = service.table('floor_plan_scans').select('*').eq('id', scan['id']).single().execute().data
    import httpx
    public_url = f'{settings["API_URL"]}/storage/v1/object/public/{BUCKET}/{stored["object_key"]}'
    assert httpx.get(public_url).status_code != 200
    for browser in (owner_client, recipient_client, anonymous_client):
        with pytest.raises(Exception):
            browser.storage.from_(BUCKET).download(stored['object_key'])
    assert api.put(endpoint + '?filename=other.usdz', headers=recipient, content=content).status_code == 409
    second = api.put(endpoint + f'?filename=replaced.usdz&expected_id={scan["id"]}', headers=recipient, content=content)
    assert second.status_code == 200, second.text
    scan = second.json()['scan']
    with pytest.raises(Exception):
        service.storage.from_(BUCKET).download(stored['object_key'])
    published = api.patch(f'/floor-planner/plans/{plan["id"]}', headers=owner, json={'expected_revision': 1, 'visibility': 'public'})
    assert published.status_code == 200
    assert api.get(f'/floor-planner/plans/{plan["id"]}').status_code == 200
    assert api.get(endpoint).status_code == 401
    assert api.get(endpoint, headers=outsider).status_code == 404
    revoked = api.delete(f'/floor-planner/plans/{plan["id"]}/invitations/{invite["id"]}', headers=owner)
    assert revoked.status_code == 204
    assert api.get(endpoint + '/content', headers=recipient).status_code == 404
    assert api.delete(endpoint + f'?expected_id={scan["id"]}', headers=recipient).status_code == 404
    denied_rpc = service.rpc('floor_planner_set_scan', {
        'p_document_id': plan['id'], 'p_user_id': str(recipient_client.auth.get_user().user.id),
        'p_email': recipient_email, 'p_expected_id': scan['id'], 'p_scan': None,
    }).execute().data
    assert denied_rpc['status'] == 'denied'
    assert api.delete(endpoint + f'?expected_id={scan["id"]}', headers=owner).status_code == 204
    assert api.get(endpoint, headers=owner).json() == {'scan': None}
    assert api.get(f'/floor-planner/plans/{plan["id"]}', headers=owner).json()['scene'] == scene
    final = api.put(endpoint + '?filename=deletion-qa.usdz', headers=owner, content=content).json()['scan']
    stored = service.table('floor_plan_scans').select('*').eq('id', final['id']).single().execute().data
    assert api.delete(f'/floor-planner/plans/{plan["id"]}', headers=owner).status_code == 204
    queued = service.table('floor_plan_scan_cleanup').select('*').eq('object_key', stored['object_key']).execute().data
    assert len(queued) == 1
    service.table('floor_plan_scan_cleanup').update({'created_at': '2020-01-01T00:00:00Z'}).eq('object_key', stored['object_key']).execute()
    cleanup_pending(service)
    assert not service.table('floor_plan_scan_cleanup').select('*').eq('object_key', stored['object_key']).execute().data
    with pytest.raises(Exception):
        service.storage.from_(BUCKET).download(stored['object_key'])
