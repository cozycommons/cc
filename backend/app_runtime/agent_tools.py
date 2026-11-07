"""Four sandbox tools on the existing OAuth connector; never accept credentials."""
import asyncio
import os
import time
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import quote, urlsplit

import httpx
from fastmcp.exceptions import ToolError
from pydantic import Field
from cc_mcp.server import ToolProvider, check_access


def manager_url():
    value = os.environ.get('APPS_MANAGER_URL', '')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in {None, 443} or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ToolError('Apps hosting is not configured. Ask the platform owner to finish setup.')
    return value.rstrip('/')


async def request(token, method, path, data=None):
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
            result = await client.request(method, manager_url() + path,
                headers={'Authorization': 'Bearer ' + token}, json=data)
        if result.status_code >= 300:
            # Never echo arbitrary upstream error bodies, URLs, or headers.
            messages = {401: 'Sign-in expired; reconnect your agent.', 403: 'Insufficient app permissions.',
                        404: 'App or job not found.', 409: 'App already exists or is unavailable.',
                        422: 'Invalid app name, member UUID, role, or command.', 429: 'Too many active commands; wait before retrying.'}
            raise ToolError(messages.get(result.status_code, 'Apps manager is unavailable; inspect effects before retrying a write.'))
        return result.json()
    except (httpx.HTTPError, ValueError):
        raise ToolError('Apps manager is unavailable; inspect effects before retrying a write.') from None


def register_tools(mcp, context):
    async def access(level):
        from cc_mcp import server
        token = check_access(server.get_access_token(), provider, level)
        await context.signed_in_user(token)
        return token.token

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def list_apps() -> list:
        """List apps you can access, roles and published services."""
        return await request(await access('read'), 'GET', '/api/apps')

    @mcp.tool(annotations={'readOnlyHint': False, 'openWorldHint': False})
    async def create_app(name: Annotated[str, Field(min_length=1, max_length=30)]) -> dict:
        """Create a persistent app workspace and local Git repository. Requires current Cozy Commons admin status.

        Ask the user before allocating an app. Repeating a name fails without replacing it.
        The hosted pilot is for synthetic data. Use shell and commons expose to publish services.
        """
        return await request(await access('edit'), 'POST', '/api/apps', {'name': name})

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def set_app_member(app: str, user: UUID, role: Literal['viewer', 'contributor', 'none']) -> dict:
        """As owner, grant/revoke access using the exact Commons user UUID confirmed by the user.

        Contributors can read/change all app code and data. Revocation is not hostile-contributor eviction.
        """
        return await request(await access('edit'), 'PUT',
            f'/api/apps/{quote(app, safe="")}/members/{user}', {'role': role})

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': True})
    async def exec_command(app: str, command: Annotated[str, Field(min_length=1, max_length=16000)],
                           timeout: Annotated[int, Field(ge=1, le=300)] = 120) -> dict:
        """Execute shell in /workspace, wait and return bounded output and exit status.

        Requires contributor access and commons:edit even for read-only shell commands.
        Use shell for files and commons expose/unexpose for HTTP services. Use supervisor
        for persistent processes. A disconnected request may still execute; inspect before retrying.
        """
        token = await access('edit')
        base = '/api/apps/' + quote(app, safe='')
        job = await request(token, 'POST', base + '/exec', {'command': command, 'timeout': timeout})
        deadline = time.monotonic() + timeout + 15
        while True:
            result = await request(token, 'GET', base + '/jobs/' + quote(job['id'], safe=''))
            if result['status'] != 'running':
                return result
            if time.monotonic() >= deadline:
                raise ToolError('Command reporting timed out; inspect the app before retrying.')
            await asyncio.sleep(.2)


provider = ToolProvider('apps', register_tools,
    {'list_apps': 'read', 'create_app': 'edit', 'set_app_member': 'edit', 'exec_command': 'edit'},
    title='Apps', description='Persistent community app sandboxes; synthetic-data hosted pilot.',
    url='https://apps.cozycommons.dev')
