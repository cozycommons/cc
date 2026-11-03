"""Partiful tools on the shared OAuth connector (/mcp).

The Partiful account is resolved from the signed-in Commons user, never from a
pasted token: the user links it once with link_partiful_account. The legacy
token-per-call server at /partiful/mcp and the /partiful routes are unchanged.

Read-only: the one project tool merges the legacy list_events and get_event and
returns exactly what they return (no guest lists).
"""
from datetime import date as Date
import logging
import time
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import StringConstraints
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, AccountLink, ToolProvider
from . import accounts
from .accounts import AccountError
from .logic import get_event, list_events
from .partiful_client import PartifulAuthError, PartifulError

logger = logging.getLogger(__name__)

ONBOARD_URL = 'https://api.cozycommons.dev/partiful/onboard/start'
DOCS_URL = 'https://github.com/cozycommons/cc/blob/main/docs/mcp/README.md#partiful'
LINK_STEP = (f'Call link_partiful_account(api_token) once with your existing ccp_ Partiful token. No token yet? '
             f'Onboard with your phone number at POST {ONBOARD_URL}, then POST /partiful/onboard/verify with the '
             f'SMS code (see {DOCS_URL}), and link the token it returns.')
RELINK_STEP = (f'Partiful rejected the stored session. Onboard again with your phone number at POST {ONBOARD_URL}, '
               'then call link_partiful_account with the new token.')

# Same limit as /partiful/onboard: 10 attempts per hour (here per Commons user).
_LINK_ATTEMPTS: dict[str, list[float]] = {}
_LINK_LIMIT = 10
_LINK_WINDOW_S = 3600

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


def rate_check(user_id):
    now = time.time()
    attempts = [t for t in _LINK_ATTEMPTS.get(user_id, []) if now - t < _LINK_WINDOW_S]
    if len(attempts) >= _LINK_LIMIT:
        raise ToolError('Too many link attempts. Try again in an hour.')
    attempts.append(now)
    _LINK_ATTEMPTS[user_id] = attempts


def link(client, user, api_token):
    rate_check(str(user.id))
    previous = linked(client, user)
    try:
        outcome, account = accounts.link_account_to_owner(client, api_token, user.id)
    except AccountError as error:
        raise ToolError('No Partiful account matches that token. Use the ccp_ token from your Partiful onboarding '
                        f'exactly as shown, or onboard again at POST {ONBOARD_URL}.') from error
    if outcome == 'other_owner':
        raise ToolError('This Partiful account is linked to another Commons user. Sign in as that user, '
                        f'or onboard your own phone number at POST {ONBOARD_URL}.')
    if outcome not in {'linked', 'already_linked'}:
        raise ToolError('Could not link the account. Retry in a moment; nothing changed.')
    result = {'linked': True, 'status': outcome, 'account': {'id': account['id'], 'label': account['label']},
              'next_step': 'Call get_partiful_events() to list your events.'}
    if outcome == 'linked' and previous and previous['id'] != account['id']:
        result['replaced_account'] = {'id': previous['id'], 'label': previous['label']}
    return result


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

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': False})
    async def link_partiful_account(api_token: str) -> dict:
        """Link your Partiful account to your Commons sign-in once, using its existing ccp_ token.

        The token proves ownership; it is checked against its stored hash and never
        stored or returned. Afterwards the Partiful tools need no token. Linking a
        different account of yours replaces the earlier link; an account linked to
        another Commons user is refused.
        """
        return await invoke(EDIT_SCOPE, link, api_token)


provider = ToolProvider(
    'partiful', register_tools,
    {'get_partiful_events': 'read', 'link_partiful_account': 'edit'},
    title='Partiful', description='Your Partiful events: hosted, RSVP’d and invited.',
    url=DOCS_URL, status=status,
    link=AccountLink(LINK_STEP, linked=linked, tool='link_partiful_account', url=ONBOARD_URL))
