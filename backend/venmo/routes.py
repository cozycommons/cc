"""Authenticated shared Venmo previews and thumbnail proxy."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from gotrue.errors import AuthApiError
from .profiles import lookup
from .photos import thumbnail
from .photo_auth import signed_path, authorized

router = APIRouter(tags=['Venmo'])
bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, 'Sign in to continue.')
    try:
        user = request.app.state.venmo_supabase.auth.get_user(credentials.credentials).user
    except AuthApiError:
        raise HTTPException(401, 'Please sign in again.')
    if not user:
        raise HTTPException(401, 'Please sign in again.')
    return user


@router.get('/profile')
def profile(request: Request, response: Response, handle: str, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    result = lookup.lookup(handle, user.id, request.app.state.venmo_supabase)
    return {**result, 'photoUrl': signed_path(result['handle'], user.id)} if result.get('found') else result


@router.get('/photo')
def photo(request: Request, handle: str, user: str = '', expires: int = 0, sig: str = '', credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials:
        identity = current_user(request, credentials).id
    elif authorized(handle, user, expires, sig):
        identity = user
    else:
        raise HTTPException(401, 'Sign in to continue.')
    try:
        body, content_type = thumbnail(lookup.lookup(handle, identity, request.app.state.venmo_supabase))
        return Response(body, media_type=content_type, headers={'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff'})
    except Exception:
        raise HTTPException(404, 'Thumbnail unavailable.')
