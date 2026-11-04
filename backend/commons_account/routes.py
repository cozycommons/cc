"""Commons account API under /account, authenticated by the Supabase session bearer."""
from uuid import UUID

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from cc_mcp import connections
from commons_account import profile
from trips.profiles import avatar_url

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
SIGN_IN = 'Sign in to manage your Cozy Commons account.'
NOT_FOUND = 'No such agent connection.'


def client(request):
    # Uncached: a disconnect must be visible to the very next list.
    return request.app.state.mcp_supabase


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, SIGN_IN)
    try:
        user = client(request).auth.get_user(credentials.credentials).user
    except AuthApiError:
        raise HTTPException(401, 'Your session expired. Please sign in again.')
    if not user:
        raise HTTPException(401, SIGN_IN)
    if getattr(user, 'is_anonymous', False):
        raise HTTPException(403, 'Sign in with Google to manage your account.')
    return user


class ProfileChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=profile.NAME_LIMIT)
    avatar_url: Optional[str] = None


def identity(user, row):
    """What every project header shows for the signed-in user."""
    return {'user_id': str(user.id), 'email': user.email,
            'display_name': row['display_name'], 'avatar_url': avatar_url(row['avatar_url'])}


@router.get('')
def get_account(request: Request, user=Depends(current_user)):
    """The caller's Commons identity, creating the profile row on first sign-in."""
    return identity(user, profile.own_profile(client(request), user))


@router.patch('/profile')
def patch_profile(changes: ProfileChanges, request: Request, user=Depends(current_user)):
    """Name and photo for every project. Venmo stays on /trips/me, which confirms ownership."""
    write = changes.model_dump(exclude_unset=True)
    if write.get('avatar_url') is not None and avatar_url(write['avatar_url']) is None:
        raise HTTPException(400, 'Use an http(s) image URL.')
    if not write:
        return identity(user, profile.own_profile(client(request), user))
    try:
        return identity(user, profile.update_profile(client(request), user.id, write, user=user))
    except ValueError as error:
        raise HTTPException(400, str(error))


def agent_oauth(request):
    """The connector's OAuth proxy, or 503 when agent access is not configured."""
    oauth = getattr(request.app.state, 'cc_mcp_oauth', None)
    if oauth is None:
        raise HTTPException(503, 'Agent connections are unavailable.')
    return oauth


@router.get('/connections')
def list_connections(request: Request, user=Depends(current_user)):
    """Active connections. `client_name` is self-reported by the agent; show `redirect_host` beside it."""
    agent_oauth(request)
    return connections.active_connections(client(request), user.id)


@router.delete('/connections/{connection_id}', status_code=204)
async def disconnect(connection_id: str, request: Request, user=Depends(current_user)):
    """Revoke one connection's access and refresh tokens. Repeating it deletes them again."""
    oauth = agent_oauth(request)
    try:
        connection_id = str(UUID(connection_id))
    except ValueError:
        raise HTTPException(404, NOT_FOUND)
    row = await run_in_threadpool(connections.own_connection, client(request), user.id, connection_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)  # Another user's connection looks exactly like a missing one.
    # Delete the tokens first, then mark: a failure never shows "disconnected" while tokens still work.
    # Delete even when already marked: the token store, not revoked_at, decides whether tokens work.
    await oauth._revoke_proxy_token_set(row['upstream_token_id'])
    if row['revoked_at'] is None:
        await run_in_threadpool(connections.mark_revoked, client(request), row['upstream_token_id'])
    return Response(status_code=204)
