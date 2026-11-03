"""Beli tools on the shared OAuth connector (/mcp).

The Beli account is resolved from the signed-in Commons user, never from a
pasted token: the user links it once with link_beli_account. The legacy
token-per-call server at /beli/mcp is unchanged.
"""
from datetime import date as Date
import logging
import time
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, AccountLink, ToolProvider
from . import accounts
from .accounts import AccountError
from .beli_client import BeliError, BeliUnauthorized
from .logic import bookmark_name, get_recs

logger = logging.getLogger(__name__)

ONBOARD_URL = 'https://api.cozycommons.dev/beli/onboard'
DOCS_URL = 'https://github.com/cozycommons/cc/blob/main/docs/beli.md'
LINK_STEP = (f'Call link_beli_account(api_token) once with your existing ccb_ Beli token. No token yet? '
             f'Onboard with your Beli login at POST {ONBOARD_URL} (see {DOCS_URL}), then link the token it returns.')
RELINK_STEP = (f'Beli rejected the stored login. Onboard again at POST {ONBOARD_URL} with your current Beli '
               'password, then call link_beli_account with the new token.')
RECEIPTS = 'beli_agent_receipts'
NO_WRITE = {'ambiguous', 'no_results'}
# What a preview reports for a place an unfinished save may have written, mapped to the recorded status.
SETTLED = {'already_bookmarked': 'bookmarked', 'already_ranked': 'already_ranked'}
UNCONFIRMED = ('Beli did not confirm the save, so it may have landed. Call save_restaurant again with the '
               'same idempotency_key; it checks your Want to Try list and never saves twice.')
UNSETTLED = ('A save with this idempotency_key has not finished: Beli does not show {name} on your Want to Try '
             'list, so the earlier save may still be running or may have failed. Call save_restaurant again '
             'with the same idempotency_key in a minute; it records the save once Beli shows the place and '
             'never writes twice. If it never appears, add it in the Beli app.')

# Same limit as /beli/onboard: 10 attempts per Commons user per hour.
_LINK_ATTEMPTS: dict[str, list[float]] = {}
_LINK_LIMIT = 10
_LINK_WINDOW_S = 3600

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Weekday = Literal['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
Clock = Annotated[str, StringConstraints(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]


def linked(client, user):
    return accounts.linked_account_summary(client, user.id)


def status(client, user):
    account = linked(client, user)
    return {'in_use': account is not None,
            'next_step': 'Call get_restaurant_recs(neighborhood).' if account else LINK_STEP}


def beli_client(client, user):
    try:
        account = accounts.get_account_by_owner(client, user.id)
    except AccountError as error:
        if str(error) == 'no linked account':
            raise ToolError(f'Link your Beli account first: {LINK_STEP}') from error
        logger.warning('Linked Beli credentials unavailable')
        raise ToolError('Could not read your linked Beli login. Retry in a moment; nothing changed.') from error
    return account, accounts.make_client_for_account(account)


def beli_call(operation, *args):
    try:
        return operation(*args)
    except BeliUnauthorized as error:
        raise ToolError(RELINK_STEP) from error
    except BeliError as error:
        detail = f' (HTTP {error.status})' if error.status else ''
        raise ToolError(f'Beli did not answer{detail}. Retry in a moment; nothing was saved.') from error
    except ValueError as error:
        raise ToolError(f'{error}. Check the inputs and retry.') from error


def recs(client, user, neighborhood, day, time_of_day, table_size, limit):
    _account, beli = beli_client(client, user)
    return beli_call(get_recs, beli, neighborhood, day, time_of_day, table_size, limit)


def receipt(client, user, key):
    rows = (client.table(RECEIPTS).select('payload,result,created_at')
            .eq('user_id', user.id).eq('idempotency_key', key).execute().data)
    return rows[0] if rows else None


class WriteWatch:
    """Passes Beli calls through and notes whether a write request was started."""

    def __init__(self, beli):
        self.beli, self.sent = beli, False

    def api_with_reauth(self, path, method='GET', body=None):
        if method != 'GET':
            self.sent = True
        return self.beli.api_with_reauth(path, method, body)


def settle(client, user, beli, key, fingerprint):
    """Resolve a reserved key with no recorded result by looking for the place on Beli.

    The save that reserved it may still be running, or may have stopped after Beli
    took the write. Its age cannot tell those apart, so this never writes: the key is
    marked done only once the place shows up on the user's lists.
    """
    name = fingerprint['name']
    try:
        check = bookmark_name(beli, name, fingerprint['city'], True)
    except BeliUnauthorized as error:
        raise ToolError(RELINK_STEP) from error
    except (BeliError, ValueError) as error:
        raise ToolError(UNSETTLED.format(name=name)) from error
    if check['status'] not in SETTLED:
        raise ToolError(UNSETTLED.format(name=name))
    result = {'dry_run': False, **check, 'status': SETTLED[check['status']]}
    (client.table(RECEIPTS).update({'result': result})
     .eq('user_id', user.id).eq('idempotency_key', key).is_('result', 'null').execute())
    return result


def replay(client, user, beli, key, found, fingerprint):
    if found['payload'] != fingerprint:
        raise ToolError('This idempotency_key was used with different details. Use a new key for a new save.')
    if found['result'] is not None:
        return found['result']
    return settle(client, user, beli, key, fingerprint)


def save(client, user, name, city, key, dry_run):
    """Bookmark through the existing confidence-gated flow; commits are receipted.

    Preview never reserves a key. A commit reserves the key before writing to Beli,
    so a concurrent retry cannot write twice. The reservation is released only when
    no write request was sent (ambiguous, no match, or a failure before the write);
    after an unconfirmed write it stays until settle finds the place on Beli.
    """
    account, beli = beli_client(client, user)
    fingerprint = {'account_id': account['id'], 'name': name, 'city': city}
    if dry_run:
        return {'dry_run': True, **beli_call(bookmark_name, beli, name, city, True)}
    found = receipt(client, user, key)
    if found:
        return replay(client, user, beli, key, found, fingerprint)
    reserved = (client.table(RECEIPTS).upsert(
        {'user_id': user.id, 'idempotency_key': key, 'payload': fingerprint},
        on_conflict='user_id,idempotency_key', ignore_duplicates=True).execute().data)
    if not reserved:
        return replay(client, user, beli, key, receipt(client, user, key), fingerprint)

    def release():
        (client.table(RECEIPTS).delete().eq('user_id', user.id).eq('idempotency_key', key)
         .is_('result', 'null').execute())

    watch = WriteWatch(beli)
    try:
        result = {'dry_run': False, **beli_call(bookmark_name, watch, name, city, False)}
    except Exception as error:
        if not watch.sent:
            release()
            raise
        logger.warning('Beli bookmark write unconfirmed: %s', type(error).__name__)
        raise ToolError(UNCONFIRMED) from error
    if result['status'] in NO_WRITE:
        release()
        return result
    (client.table(RECEIPTS).update({'result': result})
     .eq('user_id', user.id).eq('idempotency_key', key).execute())
    return result


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
        raise ToolError('No Beli account matches that token. Use the ccb_ token from your Beli onboarding '
                        f'exactly as shown, or onboard again at POST {ONBOARD_URL}.') from error
    if outcome == 'other_owner':
        raise ToolError('This Beli account is linked to another Commons user. Sign in as that user, '
                        f'or onboard your own Beli login at POST {ONBOARD_URL}.')
    if outcome not in {'linked', 'already_linked'}:
        raise ToolError('Could not link the account. Retry in a moment; nothing changed.')
    result = {'linked': True, 'status': outcome, 'account': {'id': account['id'], 'label': account['label']},
              'next_step': 'Call get_restaurant_recs(neighborhood) or save_restaurant(name, idempotency_key).'}
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
            logger.warning('Beli connector call failed: %s', type(error).__name__)
            raise ToolError('The Beli request failed. Retry in a moment with the same arguments.') from error

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def get_restaurant_recs(
        neighborhood: Text, day: Date | Weekday | None = None, time: Clock | None = None,
        table_size: Annotated[int, Field(strict=True, ge=1, le=20)] = 2,
        limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10,
    ) -> dict:
        """Restaurant recommendations for a neighborhood from your linked Beli account.

        Your Want to Try bookmarks (ranked by your Beli scores) come first, then Beli
        trending. Each rec has its Beli business id, hours, open-at-time status and
        reservation slots. day: YYYY-MM-DD or a lowercase weekday (default today, New York
        time). time: 24-hour HH:MM.
        """
        when = day.isoformat() if isinstance(day, Date) else day
        return await invoke(READ_SCOPE, recs, neighborhood, when, time, table_size, limit)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': True})
    async def save_restaurant(name: Text, idempotency_key: Key, city: Text | None = None,
                              dry_run: Annotated[bool, Field(strict=True)] = True) -> dict:
        """Preview first, then save a restaurant to your Beli Want to Try list.

        Only an exact or near-exact name match is saved. An ambiguous name returns
        status "ambiguous" with candidates and saves nothing; refine the name or add a
        city and preview again. Places you already saved or ranked are reported, never
        duplicated. Same key and details returns the original result.
        """
        return await invoke(EDIT_SCOPE, save, name, city, idempotency_key, dry_run)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': False})
    async def link_beli_account(api_token: str) -> dict:
        """Link your Beli account to your Commons sign-in once, using its existing ccb_ token.

        The token proves ownership; it is checked against its stored hash and never
        stored or returned. Afterwards the Beli tools need no token. Linking a different
        account of yours replaces the earlier link; an account linked to another Commons
        user is refused.
        """
        return await invoke(EDIT_SCOPE, link, api_token)


provider = ToolProvider(
    'beli', register_tools,
    {'get_restaurant_recs': 'read', 'save_restaurant': 'edit', 'link_beli_account': 'edit'},
    title='Beli', description='Restaurant recommendations and your Beli Want to Try list.',
    url=DOCS_URL, status=status,
    link=AccountLink(LINK_STEP, linked=linked, tool='link_beli_account', url=ONBOARD_URL))
