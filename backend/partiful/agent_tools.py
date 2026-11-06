"""Partiful tools on the shared OAuth connector (/mcp).

The Partiful account is resolved from the signed-in Commons user, never from a
pasted token: the user connects it on the account page. The legacy
token-per-call server at /partiful/mcp and the /partiful routes are unchanged.

Read-only: the one project tool merges the legacy list_events and get_event and
returns exactly what they return (no guest lists).
"""
from datetime import date as Date
import logging
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import StringConstraints
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import READ_SCOPE, AccountLink, ToolProvider
from . import accounts
from .accounts import AccountError
from .logic import get_event, list_events
from .partiful_client import PartifulAuthError, PartifulError

logger = logging.getLogger(__name__)

ACCOUNT_URL = 'https://cozycommons.dev/account#partiful'
DOCS_URL = 'https://github.com/cozycommons/cc/blob/main/docs/mcp/README.md#partiful'
# Agents never collect a Partiful SMS code or ccp_ token: the user connects Partiful on the account page.
LINK_STEP = (f'Ask the user to connect Partiful at {ACCOUNT_URL} with their phone number and the code Partiful '
             'texts them, then call this tool again. Do not ask for the code or a ccp_ token in chat.')
RELINK_STEP = (f'Partiful rejected the stored session. Ask the user to sign in to Partiful again at {ACCOUNT_URL}, '
               'then retry. Do not ask for the texted code in chat.')


EventId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100,
                                           pattern=r'^[A-Za-z0-9_-]+$')]


def linked(client, user):
    return accounts.linked_account_summary(client, user.id)


def status(client, user):
    account = linked(client, user)
    return {'in_use': account is not None,
            'next_step': 'Call get_partiful_events() to list your events.' if account else LINK_STEP}


def partiful_client(client, user):
    try:
        account = accounts.get_account_by_owner(client, user.id)
    except AccountError as error:
        if str(error) == 'no linked account':
            raise ToolError(f'Link your Partiful account first: {LINK_STEP}') from error
        logger.warning('Linked Partiful credentials unavailable')
        raise ToolError('Could not read your linked Partiful session. Retry in a moment.') from error
    return accounts.make_client_for_account(client, account)


def partiful_call(operation, *args):
    try:
        return operation(*args)
    except PartifulAuthError as error:
        raise ToolError(RELINK_STEP) from error
    except PartifulError as error:
        if error.status == 404:
            raise ToolError('Event not found. Call get_partiful_events() without event_id to list your '
                            'events and their ids.') from error
        detail = f' (HTTP {error.status})' if error.status else ''
        raise ToolError(f'Partiful did not answer{detail}. Retry in a moment.') from error
    except ValueError as error:
        if str(error) == 'event not found':
            raise ToolError('Event not found. Call get_partiful_events() without event_id to list your '
                            'events and their ids.') from error
        raise ToolError(f'{error}. Check the inputs and retry.') from error


def events(client, user, event_id, scope, start, end):
    if event_id is not None and (scope is not None or start is not None or end is not None):
        raise ToolError('Pass event_id alone for one event, or omit it and filter the list with scope, start and end.')
    partiful = partiful_client(client, user)
    if event_id is not None:
        return partiful_call(get_event, partiful, event_id)
    return partiful_call(list_events, partiful, scope or 'all', start and start.isoformat(), end and end.isoformat())


def register_tools(mcp, context):
    async def invoke(scope, operation, *args):
        access = context.need_scope(scope)
        user = await context.signed_in_user(access)
        try:
            return await run_in_threadpool(operation, context.service_client, user, *args)
        except ToolError:
            raise
        except Exception as error:
            logger.warning('Partiful connector call failed: %s', type(error).__name__)
            raise ToolError('The Partiful request failed. Retry in a moment with the same arguments.') from error

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def get_partiful_events(event_id: EventId | None = None,
                                  scope: Literal['all', 'hosted', 'rsvps', 'invited'] | None = None,
                                  start: Date | None = None, end: Date | None = None) -> dict:
        """Your Partiful events, or one event's details.

        Without event_id, lists events: scope "all" (default; hosted + RSVP'd +
        invited, deduplicated), "hosted", "rsvps" (you responded) or "invited"
        (every invite, any status), each with your own RSVP status. start/end
        (YYYY-MM-DD, inclusive) bound the event date. With event_id, returns that
        event's details. Guest lists are never returned.
        """
        return await invoke(READ_SCOPE, events, event_id, scope, start, end)


provider = ToolProvider(
    'partiful', register_tools,
    {'get_partiful_events': 'read'},
    title='Partiful', description='Your Partiful events: hosted, RSVP’d and invited.',
    url=DOCS_URL, status=status,
    link=AccountLink(LINK_STEP, linked=linked, url=ACCOUNT_URL))
