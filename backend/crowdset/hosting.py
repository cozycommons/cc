from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException

from .config import env


COOKIE = '__Secure-crowdset'


class HostedAccess:
    def __init__(self):
        self.origin = env('CROWDSET_ORIGIN', '').rstrip('/')
        self.url = env('CROWDSET_AUTH_URL', '').rstrip('/')
        self.key = env('CROWDSET_AUTH_KEY', '')
        self.root = env('CROWDSET_DATA_DIR')
        if not self.origin:
            return
        origin = urlsplit(self.origin)
        auth = urlsplit(self.url)
        if (origin.scheme != 'https' or not origin.hostname or origin.path or origin.query or origin.fragment
                or origin.username or origin.port not in (None, 443)
                or auth.scheme != 'https' or not auth.hostname or not auth.hostname.endswith('.supabase.co')
                or auth.path or auth.query or auth.fragment or auth.username or auth.port not in (None, 443)
                or not self.key or self.key.startswith('sb_secret_') or not self.root):
            raise RuntimeError('Hosted Crowdset requires an HTTPS origin, Supabase Auth URL/public key, and persistent data directory.')

    async def user(self, token):
        if not token or len(token) > 8192:
            raise HTTPException(401, 'Sign in to continue.')
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f'{self.url}/auth/v1/user', headers={
                    'apikey': self.key, 'Authorization': f'Bearer {token}',
                })
            if response.status_code in (401, 403):
                raise HTTPException(401, 'Sign in to continue.')
            if response.status_code != 200:
                raise HTTPException(503, 'Sign-in verification is unavailable. Try again.')
            user = response.json()
            if user.get('is_anonymous') or not user.get('email_confirmed_at'):
                raise HTTPException(403, 'Use a verified Cozy Commons account.')
            return str(UUID(user['id']))
        except (httpx.RequestError, ValueError, KeyError) as exc:
            raise HTTPException(503, 'Sign-in verification is unavailable. Try again.') from exc
