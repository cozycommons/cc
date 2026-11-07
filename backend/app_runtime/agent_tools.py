"""Minimal sandbox tools on the existing OAuth connector; never accept credentials."""
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
from .tool_helpers import transfer_request, transfer_response, snapshot_request, validate_exec


def manager_url():
    value = os.environ.get('APPS_MANAGER_URL', '')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in {None, 443} or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ToolError('Apps hosting is not configured. Ask the platform owner to finish setup.')
    return value.rstrip('/')


async def request(token, method, path, data=None, *, content=None):
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
            result = await client.request(method, manager_url() + path,
                headers={'Authorization': 'Bearer ' + token}, json=data, content=content)
        if result.status_code >= 300:
            # Never echo arbitrary upstream error bodies, URLs, or headers.
            messages = {401: 'Sign-in expired; reconnect your agent.', 403: 'Insufficient app permissions.',
                        404: 'App or job not found.', 409: 'Conflict: key reused, app unavailable, or operation outcome unknown; inspect before using a new key.',
                        413: 'Transfer exceeds 16 MiB; split using shell.',
                        422: 'Invalid app name, member UUID, role, or command.', 429: 'Command, transfer or sign-in concurrency limit reached; wait before retrying.'}
            raise ToolError(messages.get(result.status_code, 'Apps manager is unavailable; inspect effects before retrying a write.'))
        if method == 'GET' and '/transfer?' in path:
            return transfer_response(result)
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
    async def list_apps(details: bool = False) -> list:
        """List accessible apps, roles and routes. details adds platform limits, usage and lifecycle diagnostics."""
        return await request(await access('read'), 'GET', '/api/apps?details=true' if details else '/api/apps')

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
    async def exec_command(app: str, command: Annotated[str | None, Field(max_length=16000)] = None,
                           timeout: Annotated[int, Field(ge=1, le=300)] = 120,
                           idempotency_key: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
                           job_id: str | None = None, after: int = 0,
                           wait_ms: Annotated[int, Field(ge=0, le=10000)] = 1000, cancel: bool = False) -> dict:
        """Start shell or reconnect using job_id; returns incremental output and next_cursor.

        Supply a unique idempotency_key when starting; retry the same key/command/timeout
        to recover a disconnected start without rerunning it. Reconnect with after=next_cursor.
        wait_ms bounds polling; running jobs continue after tool return. cancel stops the command
        process group. Output retains 64 KiB; truncated reports a cursor gap. Manager restart
        reports interrupted, never reruns. Requires contributor and edit scope even for reads.
        Use supervisor for services and commons expose/unexpose for routes.
        """
        validate_exec(command, job_id, cancel, after, wait_ms)
        token = await access('edit')
        base = '/api/apps/' + quote(app, safe='')
        if command is not None:
            data = {'command': command, 'timeout': timeout}
            if idempotency_key is not None:
                data['idempotency_key'] = idempotency_key
            job = await request(token, 'POST', base + '/exec', data)
            job_id = job['id']
        path = base + '/jobs/' + quote(job_id, safe='')
        if cancel:
            await request(token, 'POST', path + '/cancel')
        deadline = time.monotonic() + wait_ms / 1000
        while True:
            result = await request(token, 'GET', path + '?after=' + str(after))
            if result['status'] != 'running' or time.monotonic() >= deadline:
                return result
            await asyncio.sleep(.2)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def transfer_file(app: str, path: str, direction: Literal['upload', 'download'],
                            content_base64: str | None = None, sha256: str | None = None) -> dict:
        """Transfer a binary file or opaque archive under /workspace, at most 16 MiB.

        Upload requires base64 content and SHA-256; atomically replaces the file. Repeating
        the same upload has the same effect. Download returns base64 and checksum. Use shell
        to pack/unpack directories. Requires contributor and edit scope for both directions.
        """
        token = await access('edit')
        method, query, content = transfer_request(path, direction, content_base64, sha256)
        return await request(token, method, '/api/apps/' + quote(app, safe='') + '/transfer' + query, content=content)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def app_backups(app: str, action: Literal['list', 'create', 'restore'] = 'list',
                          idempotency_key: str | None = None, backup_id: str | None = None,
                          confirm_replace_data: bool = False) -> dict:
        """Owner-only platform snapshots. List first to obtain exact backup IDs.

        Create briefly stops a running app; retains the newest three snapshots. Create/restore
        require a unique idempotency key; retry the same request/key after disconnects. Restore
        replaces ALL workspace files, data and Git history; obtain explicit user approval before
        setting confirm_replace_data. Unknown outcomes require inspection, never a blind new key.
        Inventory needs read scope; create/restore need edit scope.
        """
        token = await access('read' if action == 'list' else 'edit')
        method, path, data = snapshot_request(action, idempotency_key, backup_id, confirm_replace_data)
        return await request(token, method, '/api/apps/' + quote(app, safe='') + path, data)


provider = ToolProvider('apps', register_tools,
    {'list_apps': 'read', 'create_app': 'edit', 'set_app_member': 'edit', 'exec_command': 'edit',
     'transfer_file': 'edit', 'app_backups': 'read'},
    title='Apps', description='Persistent community app sandboxes; synthetic-data hosted pilot.',
    url='https://apps.cozycommons.dev')
