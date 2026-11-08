"""Explicit hosted settings; local defaults remain loopback-only."""
import os
import re
from uuid import UUID
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    hosted: bool = False
    domain: str = 'localhost'
    prefix: str = 'cc-apps-local-'
    image: str = 'cc-apps-runtime:local'
    supabase_url: str = ''
    publishable_key: str = ''
    mcp_client_id: str = ''
    caller_secret: str = ''

    @classmethod
    def load(cls):
        mode = os.environ.get('APPS_MODE', 'local')
        if mode == 'local':
            return cls()
        if mode != 'hosted':
            raise ValueError('APPS_MODE must be local or hosted')
        domain = os.environ.get('APPS_DOMAIN', '')
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
            raise ValueError('APPS_DOMAIN must be a DNS domain')
        url = os.environ.get('APPS_SUPABASE_URL', '')
        if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', url):
            raise ValueError('APPS_SUPABASE_URL must be an exact hosted Supabase origin')
        key = os.environ.get('APPS_SUPABASE_PUBLISHABLE_KEY', '')
        if not key.startswith('sb_publishable_'):
            raise ValueError('Use a Supabase publishable key, never a service-role key')
        image = os.environ.get('APPS_RUNTIME_IMAGE', '')
        if not re.fullmatch(r'[a-zA-Z0-9./_:@-]+', image):
            raise ValueError('APPS_RUNTIME_IMAGE is required')
        client_id = os.environ.get('APPS_MCP_OAUTH_CLIENT_ID', '')
        try:
            if str(UUID(client_id)) != client_id:
                raise ValueError()
        except ValueError:
            raise ValueError('APPS_MCP_OAUTH_CLIENT_ID must identify the official Commons OAuth client') from None
        caller = os.environ.get('APPS_MANAGER_CALLER_SECRET', '')
        if not re.fullmatch(r'[A-Za-z0-9+/=_-]{32,256}', caller):
            raise ValueError('APPS_MANAGER_CALLER_SECRET must be a random secret of at least 32 characters')
        return cls(True, domain, 'cc-apps-hosted-', image, url, key, client_id, caller)

    @property
    def portal(self):
        return 'apps.' + self.domain if self.hosted else 'admin.localhost'

    def url(self, host):
        return f'https://{host}' if self.hosted else f'http://{host}:8090'
