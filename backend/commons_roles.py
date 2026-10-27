"""Live Commons roles; RPCs bypass the product query cache."""
from fastapi import HTTPException
from postgrest.exceptions import APIError


def role_rpc(client, name, params):
    try:
        return client.rpc(name, params).execute().data
    except APIError as exc:
        messages = {
            'PT403': (403, 'Access denied.'),
            'PT404': (404, 'Account not found.'),
            'PT409': (409, 'Role changed or the last admin would be removed. Refresh before trying again.'),
            'PT422': (422, 'Only verified accounts can become admins.'),
        }
        status, message = messages.get(exc.code, (503, 'Account roles are temporarily unavailable.'))
        raise HTTPException(status, message) from exc
    except Exception as exc:
        raise HTTPException(503, 'Account roles are temporarily unavailable.') from exc


def user_role(client, user_id):
    return role_rpc(client, 'commons_get_role', {'p_user_id': str(user_id)})
