"""Member-scoped hosted apps for the Commons home page."""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastmcp.exceptions import ToolError
from .agent_tools import request

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


@router.get('/apps/catalog')
async def catalog(response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    response.headers['Cache-Control'] = 'private, no-store'
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Sign in to view your apps')
    try:
        apps = await request(credentials.credentials, 'GET', '/api/apps')
    except ToolError:
        raise HTTPException(503, 'Apps are unavailable; try again shortly') from None
    return [{'name': app['name'], 'status': app['status'], 'url': app['routes']['default']['url']}
            for app in apps if app.get('routes', {}).get('default', {}).get('url')]
