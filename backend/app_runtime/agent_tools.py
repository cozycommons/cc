"""Minimal sandbox tools on the existing OAuth connector; never accept credentials."""
import inspect
import os
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import quote, urlsplit

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.server.middleware import Middleware
from mcp.types import ToolAnnotations
from pydantic import Field
from cc_mcp.server import ToolProvider, check_access
from .text_file_models import TextReadSpec, TextEditSpec
from .tool_helpers import MCP_TRANSFER_LIMIT, transfer_request, transfer_response, snapshot_request, validate_exec, manager_error, execution_request, job_query, uncertain_job, cancellation_result


def manager_url():
    value = os.environ.get('APPS_MANAGER_URL', '')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in {None, 443} or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ToolError('Apps hosting is not configured. Ask the platform owner to finish setup.')
    return value.rstrip('/')


def caller_secret():
    # Proves to the manager that the request came from this backend, not just
    # from someone holding the user's Supabase token.
    value = os.environ.get('APPS_MANAGER_CALLER_SECRET', '')
    if len(value) < 32:
        raise ToolError('Apps hosting is not configured. Ask the platform owner to finish setup.')
    return value


async def request(token, method, path, data=None, *, content=None):
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
            result = await client.request(method, manager_url() + path, json=data, content=content,
                headers={'Authorization': 'Bearer ' + token, 'X-Commons-Apps-Caller': caller_secret()})
        if result.status_code >= 300:
            # Never echo arbitrary upstream error bodies, URLs, or headers.
            messages = {401: 'Sign-in expired; reconnect your agent.', 403: 'Insufficient app permissions.',
                        404: 'App or job not found; snapshot may also be unavailable.', 409: 'Conflict: key reused, app unavailable, or operation outcome unknown; inspect before using a new key.',
                        413: 'Transfer exceeds the size limit (2 MiB MCP; 16 MiB binary HTTP/CLI); split using shell.',
                        422: 'Invalid app name, member UUID, role, command, output cursor, file transfer, or snapshot parameters.', 429: 'Command, transfer or sign-in concurrency limit reached; wait before retrying.'}
            raise ToolError(manager_error(result) or messages.get(result.status_code, 'Apps manager is unavailable; inspect effects before retrying a write.'))
        if method == 'GET' and '/transfer?' in path:
            return transfer_response(result, max_bytes=MCP_TRANSFER_LIMIT)
        return result.json()
    except (httpx.HTTPError, ValueError):
        raise ToolError('Apps manager is unavailable; inspect effects before retrying a write.') from None


def register_tools(mcp, context):
    arguments = {}

    class StrictAppArguments(Middleware):
        async def on_call_tool(self, context, call_next):
            allowed = arguments.get(context.message.name)
            if allowed is not None and set(context.message.arguments or {}) - allowed:
                raise ToolError('Unexpected Apps tool arguments; use the published schema.')
            return await call_next(context)

    mcp.add_middleware(StrictAppArguments())

    def app_tool(*, annotations):
        def register(function):
            arguments[function.__name__] = set(inspect.signature(function).parameters)
            tool = Tool.from_function(function, annotations=ToolAnnotations(**annotations))
            tool.parameters['additionalProperties'] = False
            mcp.add_tool(tool)
            return function
        return register

    async def access(level):
        from cc_mcp import server
        token = check_access(server.get_access_token(), provider, level)
        await context.signed_in_user(token)
        return token.token

    @app_tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def list_apps(details: bool = False) -> list:
        """List accessible apps, roles and routes. details adds platform limits, usage and lifecycle diagnostics."""
        return await request(await access('read'), 'GET', '/api/apps?details=true' if details else '/api/apps')

    @app_tool(annotations={'readOnlyHint': False, 'openWorldHint': False})
    async def create_app(name: Annotated[str, Field(min_length=1, max_length=30)]) -> dict:
        """Create a persistent app workspace and local Git repository. Requires current Cozy Commons admin status.

        Ask the user before allocating an app. Repeating a name fails without replacing it.
        The hosted pilot is for synthetic data. Use shell and commons expose to publish services.
        """
        return await request(await access('edit'), 'POST', '/api/apps', {'name': name})

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def set_app_member(app: str, user: UUID, role: Literal['viewer', 'contributor', 'none']) -> dict:
        """As owner, grant/revoke access using the exact Commons user UUID confirmed by the user.

        Contributors can read/change all app code and data. Revocation is not hostile-contributor eviction.
        """
        return await request(await access('edit'), 'PUT',
            f'/api/apps/{quote(app, safe="")}/members/{user}', {'role': role})

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': True})
    async def exec_command(app: str, command: Annotated[str | None, Field(max_length=16000)] = None,
                           timeout: Annotated[int, Field(ge=1, le=300)] = 120,
                           idempotency_key: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
                           job_id: str | None = None, after: int = 0,
                           wait_ms: Annotated[int, Field(ge=0, le=10000)] = 1000, cancel: bool = False,
                           cwd: Annotated[str | None, Field(max_length=2000)] = None,
                           timeout_seconds: Annotated[int | None, Field(ge=1, le=300)] = None,
                           max_output_bytes: Annotated[int, Field(ge=4, le=65536)] = 4096) -> dict:
        """Start a fresh noninteractive shell job. Always supply idempotency_key for safe retries.

        Retry identical command/cwd/timeout with the SAME key after a lost start response.
        Returns job_id, state, bounded UTF-8 output and next_cursor; use job_read/job_cancel.
        cwd defaults to /workspace; shell cwd/env do not persist. timeout_seconds defaults 120.
        Exit failures are job results; cancellation is not rollback. Use supervisor for services
        and commons expose/unexpose for routes. Contributor and edit scope required.
        Legacy timeout/job_id/after/cancel and starts without a key remain temporarily supported.
        """
        validate_exec(command, job_id, cancel, after, wait_ms)
        query = job_query(after, wait_ms, max_output_bytes, completion=True)
        if job_id is not None and (cwd is not None or timeout_seconds is not None or idempotency_key is not None):
            raise ValueError('Continuation takes app/job_id/cursor/wait/output only; use job_read')
        token = await access('edit')
        base = '/api/apps/' + quote(app, safe='')
        started = command is not None
        if started:
            data = execution_request(command, timeout, idempotency_key, cwd, timeout_seconds)
            job = await request(token, 'POST', base + '/exec', data)
            job_id = job['id']
        path = base + '/jobs/' + quote(job_id, safe='')
        if cancel:
            await request(token, 'POST', path + '/cancel')
        try:
            return await request(token, 'GET', path + query)
        except ToolError:
            if not started:
                raise
            return uncertain_job(job_id)

    @app_tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def job_read(app: str, job_id: Annotated[str, Field(min_length=1)],
                       cursor: Annotated[int, Field(ge=0)] = 0,
                       wait_ms: Annotated[int, Field(ge=0, le=10000)] = 1000,
                       max_output_bytes: Annotated[int, Field(ge=4, le=65536)] = 4096) -> dict:
        """Read job state and bounded new UTF-8 output; never starts work. Resume next_cursor.

        Output retains the last 64 KiB; output_gap and available_from identify discarded bytes.
        wait_ms briefly waits for output/completion. Requires contributor and edit scope.
        """
        query = job_query(cursor, wait_ms, max_output_bytes)
        return await request(await access('edit'), 'GET', '/api/apps/' + quote(app, safe='') +
                             '/jobs/' + quote(job_id, safe='') + query)

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def job_cancel(app: str, job_id: Annotated[str, Field(min_length=1)]) -> dict:
        """Request job cancellation. Read until terminal; requested does not mean stopped or undone.

        Requires contributor and edit scope, including after reconnect or membership changes.
        """
        result = await request(await access('edit'), 'POST', '/api/apps/' + quote(app, safe='') +
                               '/jobs/' + quote(job_id, safe='') + '/cancel')
        return cancellation_result(result)

    @app_tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def read_files(app: str, files: Annotated[list[TextReadSpec], Field(min_length=1, max_length=32)],
                         max_output_bytes: Annotated[int, Field(ge=1, le=65536)] = 65536) -> dict:
        """Read bounded UTF-8 text from workspace-relative paths, with whole-file SHA-256.

        Returns completeness/truncation and newline metadata; a hash does not mean full content.
        Shared content budget is allocated fairly. Files at most 1 MiB; use shell for larger,
        binary or minified files. Read requires contributor and edit scope, because app files
        can contain secrets. No line numbers inserted. Symlinks/hardlinks are unsupported.
        """
        data = {'files': [item.model_dump(exclude_none=True) for item in files],
                'max_output_bytes': max_output_bytes}
        return await request(await access('edit'), 'POST', '/api/apps/' + quote(app, safe='') + '/text/read', data)

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def edit_files(app: str, files: Annotated[list[TextEditSpec], Field(min_length=1, max_length=16)]) -> dict:
        """Replace unique exact text matches after whole-file SHA-256 checks. Reread on conflict.

        Validate the batch before writing; no crash-safe multi-file transaction. Preserves
        unrelated bytes, newlines and mode bits. Structured operations serialize per app;
        arbitrary shell/app writers bypass that lock. Workspace-relative paths, 1 MiB files.
        """
        return await request(await access('edit'), 'POST', '/api/apps/' + quote(app, safe='') + '/text/edit',
                             {'files': [item.model_dump() for item in files]})

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def write_file(app: str, path: Annotated[str, Field(min_length=1, max_length=2000)],
                         content: Annotated[str, Field(max_length=1048576)],
                         expected_sha256: str | None) -> dict:
        """Create/replace UTF-8 text up to 1 MiB; path is workspace-relative, parent must exist.

        expected_sha256=null is create-only. Replacement needs the last observed whole-file hash.
        Never overwrite with a truncated read. Preserves existing mode; atomic file replacement,
        not protection against arbitrary concurrent shell/app writers. Contributor/edit required.
        """
        return await request(await access('edit'), 'POST', '/api/apps/' + quote(app, safe='') + '/text/write',
                             {'path': path, 'content': content, 'expected_sha256': expected_sha256})

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
    async def transfer_file(app: str, path: str, direction: Literal['upload', 'download'],
                            content_base64: str | None = None, sha256: str | None = None) -> dict:
        """Transfer a binary file or opaque archive under /workspace, at most 2 MiB over MCP.

        Upload requires base64 content and SHA-256; atomically replaces the file. Repeating
        the same upload has the same effect. Download returns base64 and checksum. Use shell
        to pack/unpack or split directories; binary HTTP/CLI supports 16 MiB. Requires contributor and edit scope for both directions.
        """
        token = await access('edit')
        method, query, content = transfer_request(path, direction, content_base64, sha256)
        return await request(token, method, '/api/apps/' + quote(app, safe='') + '/transfer' + query, content=content)

    @app_tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': False})
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
     'job_read': 'edit', 'job_cancel': 'edit', 'read_files': 'edit', 'edit_files': 'edit', 'write_file': 'edit',
     'transfer_file': 'edit', 'app_backups': 'read'},
    title='Apps', description='Persistent community app sandboxes; synthetic-data hosted pilot.',
    url='https://apps.cozycommons.dev')
