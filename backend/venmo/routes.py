"""Authenticated shared Venmo previews and thumbnail proxy."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from gotrue.errors import AuthApiError
from .profiles import lookup
from .photos import thumbnail
from .photo_auth import signed_path, authorized, version

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
    response.headers['Cache-Control'] = 'private, max-age=300'
    result = lookup.lookup(handle, user.id, request.app.state.venmo_supabase)
    return {**result, 'photoUrl': signed_path(result['handle'], user.id, result['photoUrl'])} if result.get('found') else result


@router.get('/photo')
def photo(request: Request, handle: str, user: str = '', expires: int = 0, sig: str = '', v: str = '', credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials:
        identity = current_user(request, credentials).id
    elif authorized(handle, user, expires, sig, v):
        identity = user
    else:
        raise HTTPException(401, 'Sign in to continue.')
    try:
        db = request.app.state.venmo_supabase
        result = lookup.lookup(handle, identity, db)
        if v and version(result.get('photoUrl', '')) != v:
            raise ValueError('Photo version changed')
        body, content_type = thumbnail(result, db)
        return Response(body, media_type=content_type, headers={'Cache-Control': 'private, max-age=21600, immutable', 'X-Content-Type-Options': 'nosniff'})
    except Exception:
        raise HTTPException(404, 'Thumbnail unavailable.')
