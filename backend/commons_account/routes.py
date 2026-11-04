"""Commons account API under /account, authenticated by the Supabase session bearer."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError
from starlette.concurrency import run_in_threadpool

from cc_mcp import connections

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
    """Revoke one connection's access and refresh tokens. Repeating it is a no-op."""
    oauth = agent_oauth(request)
    try:
        connection_id = str(UUID(connection_id))
    except ValueError:
        raise HTTPException(404, NOT_FOUND)
    row = await run_in_threadpool(connections.own_connection, client(request), user.id, connection_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)  # Another user's connection looks exactly like a missing one.
    if row['revoked_at'] is None:
        # Delete the tokens first, then mark: a failure never shows "disconnected" while tokens still work.
        await oauth._revoke_proxy_token_set(row['upstream_token_id'])
        await run_in_threadpool(connections.mark_revoked, client(request), row['upstream_token_id'])
    return Response(status_code=204)
