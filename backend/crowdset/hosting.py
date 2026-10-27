import asyncio
import logging
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException

from .config import env


COOKIE = '__Secure-crowdset'
logger = logging.getLogger(__name__)


class HostedAccess:
    def __init__(self):
        self.origin = env('CROWDSET_ORIGIN', '').rstrip('/')
        self.url = env('CROWDSET_AUTH_URL', '').rstrip('/')
        self.key = env('CROWDSET_AUTH_KEY', '')
        self.root = env('CROWDSET_DATA_DIR')
        self.client = None
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
            if self.client is None:
                self.client = httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3))
            for attempt in range(3):
                try:
                    response = await self.client.get(f'{self.url}/auth/v1/user', headers={
                        'apikey': self.key, 'Authorization': f'Bearer {token}',
                    })
                except httpx.RequestError as exc:
                    reason = type(exc).__name__
                else:
                    if response.status_code != 429 and response.status_code < 500:
                        break
                    reason = f'HTTP {response.status_code}'
                logger.warning('Crowdset sign-in verification attempt %s/3 failed: %s', attempt + 1, reason)
                if attempt == 2:
                    raise HTTPException(503, 'Sign-in verification is temporarily unavailable. Existing upload progress is retained; retry shortly.')
                await asyncio.sleep(0.25 * 2 ** attempt)
            if response.status_code in (401, 403):
                raise HTTPException(401, 'Sign in to continue.')
            if response.status_code != 200:
                logger.warning('Crowdset sign-in verification returned unexpected HTTP %s', response.status_code)
                raise HTTPException(503, 'Sign-in verification is unavailable. Try again.')
            user = response.json()
            if user.get('is_anonymous') or not user.get('email_confirmed_at'):
                raise HTTPException(403, 'Use a verified Cozy Commons account.')
            metadata = user.get('user_metadata') or {}
            name = None
            if isinstance(metadata, dict):
                for field in ('full_name', 'name', 'display_name', 'preferred_username'):
                    value = metadata.get(field)
                    if isinstance(value, str) and value.strip():
                        name = ' '.join(value.split())[:80]
                        break
            user_id = str(UUID(user['id']))
            try:
                roles = await self.client.get(f'{self.url}/rest/v1/commons_user_roles',
                    params={'select': 'role', 'user_id': f'eq.{user_id}'},
                    headers={'apikey': self.key, 'Authorization': f'Bearer {token}', 'Cache-Control': 'no-cache'})
                if roles.status_code != 200:
                    raise HTTPException(503, 'Account roles are temporarily unavailable.')
                rows = roles.json()
                if not isinstance(rows, list) or len(rows) > 1 or any(row.get('role') not in ('admin', 'member') for row in rows):
                    raise ValueError('Invalid account role response')
            except httpx.RequestError as exc:
                raise HTTPException(503, 'Account roles are temporarily unavailable.') from exc
            return user_id, name, bool(rows and rows[0]['role'] == 'admin')
        except (ValueError, KeyError) as exc:
            logger.warning('Crowdset sign-in verification returned invalid user data: %s', type(exc).__name__)
            raise HTTPException(503, 'Sign-in verification is unavailable. Try again.') from exc

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None
