"""ESPN Fantasy tools on the shared OAuth connector (/mcp).

The ESPN account is resolved from the signed-in Commons user, never from a
pasted token: the user links it once with link_espn_account. The legacy
token-per-call server at /espn/mcp, the /espn routes and espn_team_claims are
unchanged.

Fifteen legacy tools become five. Reads merge by a view or kind parameter.
Writes keep the existing propose -> approve gate: propose_fantasy_change
validates against the live league and stores a pending proposal (a dry-run
lineup run, a pending roster edit or trade) and sends nothing to ESPN.
approve_fantasy_change previews by default and, with dry_run=false, submits that
one proposal under a durable idempotency_key receipt written just before the
submission and never released. A key whose outcome was not recorded is settled
only by reading ESPN, never by submitting again. Each proposal is claimed before
it can reach ESPN, so a second key replays or rereads the first attempt.
"""
from datetime import date as Date, datetime, timedelta, timezone
import logging
import time
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, AccountLink, ToolProvider
from . import accounts, lineup, logic, roster_edits, trades, write_safety
from .accounts import AccountError
from .espn_client import EspnAuthError, EspnError
from .mcp_server import _player_trends
from .scoreboard import ScoreboardClient

logger = logging.getLogger(__name__)

ONBOARD_URL = 'https://api.cozycommons.dev/espn/onboard'
DOCS_URL = 'https://github.com/cozycommons/cc/blob/main/docs/mcp/README.md#espn'
LINK_STEP = (f'Call link_espn_account(api_token) once with your existing cce_ ESPN token. No token yet? '
             f'Onboard at POST {ONBOARD_URL} with your league_id, season and espn_s2/SWID cookies, or at POST '
             f'{ONBOARD_URL}/login with your ESPN login (see {DOCS_URL}), then link the token it returns.')
RELINK_STEP = (f'ESPN rejected the stored cookies. Onboard again at POST {ONBOARD_URL} with fresh espn_s2/SWID '
               'cookies, then call link_espn_account with the new token.')
RECEIPTS = 'espn_agent_receipts'
LINEUP_APPROVALS = 'espn_lineup_approvals'
RUN_COLUMNS = 'id,league_id,season,scoring_period_id,mode,status,plan,moves,conflicts,error,created_at'
# A lineup preview is approvable as long as a roster edit or trade proposal is.
LINEUP_TTL_MINUTES = roster_edits.EDIT_TTL_MINUTES
SLOT_NAMES = {0: 'PG', 1: 'SG', 2: 'SF', 3: 'PF', 4: 'C', 5: 'G', 6: 'F', 11: 'UTIL', 12: 'bench', 13: 'IR'}

KIND_NAMES = {'lineup': 'lineup', 'roster_edit': 'roster edit', 'trade': 'trade offer'}
ACTIVITY = {'lineup_runs': 'lineup', 'roster_edits': 'roster_edit', 'trades': 'trade'}
# Recorded outcomes. Pending rows were never claimed, so nothing was submitted.
DONE = {'executed', 'waiver_pending', 'offered', 'failed', 'expired'}

# A receipt is written just before the approval and never released, so a key
# whose outcome was not recorded can only be settled by reading ESPN.
UNCONFIRMED = ('ESPN did not confirm the {what}, so it may have gone through. Call approve_fantasy_change again '
               'with the same idempotency_key and arguments; it rereads ESPN and never submits twice.')
UNSETTLED = ('This approval is not confirmed: ESPN does not show the {what} yet ({detail}). The earlier attempt '
             'may still be running, or ESPN may apply it later. Call approve_fantasy_change again with the same '
             'idempotency_key and arguments in a minute; it never submits twice. If it never appears, ask the user '
             'to check the ESPN app before changing anything else.')
UNSETTLED_LINEUP = ('This lineup approval is not confirmed: ESPN still shows {count} lineup move(s) to make for '
                    'scoring period {period}. The earlier run may still be running. Call approve_fantasy_change '
                    'again with the same idempotency_key and arguments in a minute; it never submits twice. If '
                    'moves remain, propose the lineup again and approve that new proposal with a new key: a new run '
                    'plans from the lineup ESPN shows then, so no landed move repeats.')

# Same limit as /espn/onboard: 10 attempts per hour (here per Commons user).
_LINK_ATTEMPTS: dict[str, list[float]] = {}
_LINK_LIMIT = 10
_LINK_WINDOW_S = 3600

Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Id = Annotated[int, Field(strict=True, ge=1)]
Limit = Annotated[int, Field(strict=True, ge=1, le=200)]
Period = Annotated[int, Field(strict=True, ge=1, le=400)]
Players = Annotated[list[Id], Field(min_length=1, max_length=15)]
ProposalId = Annotated[str, StringConstraints(
    strip_whitespace=True, pattern=r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
DryRun = Annotated[bool, Field(strict=True)]
Kind = Literal['lineup', 'roster_edit', 'trade']


def linked(client, user):
    return accounts.linked_account_summary(client, user.id)


def status(client, user):
    account = linked(client, user)
    return {'in_use': account is not None,
            'next_step': "Call get_fantasy_league(view='league')." if account else LINK_STEP}


def espn_call(operation, *args, **kwargs):
    """Run reads and proposals (never an approval) with errors that name the fix."""
    try:
        return operation(*args, **kwargs)
    except EspnAuthError as error:
        raise ToolError(RELINK_STEP) from error
    except EspnError as error:
        detail = f' (HTTP {error.status})' if error.status else ''
        raise ToolError(f'ESPN did not answer{detail}. Retry in a moment; nothing was submitted.') from error
    except (roster_edits.EditStateError, trades.TradeStateError) as error:
        raise ToolError(f'{error}. Call get_fantasy_activity with that id to reconcile it from ESPN first; '
                        'nothing was submitted.') from error
    except ValueError as error:
        raise ToolError(f'{error}. Check the inputs and retry; nothing was submitted.') from error


def espn_account(client, user):
    try:
        account = accounts.get_account_by_owner(client, user.id)
    except AccountError as error:
        if str(error) == 'no linked account':
            raise ToolError(f'Link your ESPN account first: {LINK_STEP}') from error
        logger.warning('Linked ESPN credentials unavailable')
        raise ToolError('Could not read your linked ESPN cookies. Retry in a moment; nothing changed.') from error
    return account, accounts.make_client_for_account(account)


def own_team_id(espn, account):
    return lineup.find_member_team(espn.get_league(['mTeam']) or {}, account['swid']).get('id')


def league(client, user, view, team_id, limit):
    if view != 'team' and team_id is not None:
        raise ToolError("team_id is only for view='team'.")
    account, espn = espn_account(client, user)
    if view == 'league':
        result = espn_call(logic.get_league, espn)
        return {**result, 'your_team_id': espn_call(own_team_id, espn, account)}
    if view == 'standings':
        return espn_call(logic.get_standings, espn)
    if view == 'draft':
        return espn_call(logic.get_draft, espn)
    if view == 'transactions':
        return espn_call(logic.get_transactions, espn, limit)
    wanted = team_id if team_id is not None else espn_call(own_team_id, espn, account)
    try:
        return espn_call(logic.get_team, espn, wanted)
    except ToolError as error:
        if 'team not found' in str(error):
            raise ToolError(f"No team {wanted} in your league. Call get_fantasy_league(view='league') for team "
                            'ids.') from error
        raise


def trends(client, user, kind, limit):
    account, espn = espn_account(client, user)
    if kind == 'teams':
        return espn_call(logic.get_team_trends, espn)
    return espn_call(_player_trends, client, account, espn, limit)


def lineup_run(client, account_id, run_id):
    rows = (client.table('espn_lineup_runs').select(RUN_COLUMNS).eq('account_id', account_id)
            .eq('id', run_id).execute().data) or []
    return rows[0] if rows else None


def stored(client, account, espn, kind, proposal_id):
    """The caller's own proposal by id. With espn, an unresolved edit or trade is first reconciled from ESPN."""
    if kind == 'lineup':
        return lineup_run(client, account['id'], proposal_id)
    if kind == 'roster_edit':
        return roster_edits.get_edit(client, account['id'], proposal_id, account=account, client=espn)
    return trades.get_proposal(client, account['id'], proposal_id, account=account, client=espn)


def not_found(kind, proposal_id):
    activity = next(name for name, value in ACTIVITY.items() if value == kind)
    return ToolError(f'No {KIND_NAMES[kind]} {proposal_id} in your ESPN account. Call '
                     f"get_fantasy_activity(kind='{activity}') for your ids.")


def activity(client, user, kind, proposal_id, limit, scoring_period_id):
    if kind != 'lineup_runs' and scoring_period_id is not None:
        raise ToolError("scoring_period_id is only for kind='lineup_runs'.")
    account, espn = espn_account(client, user)
    if proposal_id is not None:
        row = espn_call(stored, client, account, espn, ACTIVITY[kind], proposal_id)
        if row is None:
            raise not_found(ACTIVITY[kind], proposal_id)
        return row
    if kind == 'lineup_runs':
        return espn_call(lineup.list_runs, client, account['id'], limit, scoring_period_id)
    if kind == 'roster_edits':
        return espn_call(roster_edits.list_edits, client, account['id'], limit)
    return espn_call(trades.list_proposals, client, account['id'], limit)


def slot(slot_id):
    return SLOT_NAMES.get(slot_id, f'slot {slot_id}')


def lineup_moves(plan):
    """Moves a live run would still submit: locked players' moves are never sent."""
    locked = {skip.get('player_id') for skip in plan.get('locked_skips') or []}
    return [move for move in plan.get('moves') or [] if move['playerId'] not in locked]


def lineup_summary(run):
    plan = run.get('plan') or {}
    names = {player['player_id']: player.get('name') for player in plan.get('players') or []}
    moves = lineup_moves(plan)
    described = '; '.join(f"{names.get(m['playerId']) or m['playerId']} {slot(m['fromLineupSlotId'])} -> "
                          f"{slot(m['toLineupSlotId'])}" for m in moves)
    text = [f"Lineup for scoring period {run['scoring_period_id']}: "
            + (f'{len(moves)} move(s): {described}.' if moves else 'no moves needed.')]
    sitting = sorted({c.get('player_name') or str(c.get('player_id')) for c in run.get('conflicts') or []
                      if c.get('kind') in ('slot_overflow', 'eligibility_jam', 'roster_cap')})
    if sitting:
        text.append(f"Scheduled but sitting (no legal slot): {', '.join(sitting)}.")
    if plan.get('locked_skips'):
        text.append(f"{len(plan['locked_skips'])} player(s) already locked by tip-off stay put.")
    return ' '.join(text)


def expired(created_at, minutes):
    created = roster_edits._parse_dt(created_at)
    return created is not None and datetime.now(timezone.utc) >= created + timedelta(minutes=minutes)


def describe(kind, row):
    return lineup_summary(row) if kind == 'lineup' else row.get('preview') or ''


def proposal_view(kind, row):
    summary = describe(kind, row)
    if kind == 'lineup':
        created = roster_edits._parse_dt(row.get('created_at'))
        expires = (created + timedelta(minutes=LINEUP_TTL_MINUTES)).isoformat() if created else None
        return {'kind': kind, 'proposal_id': row['id'], 'status': 'pending', 'expires_at': expires,
                'summary': summary, 'proposal': row}
    return {'kind': kind, 'proposal_id': row['id'], 'status': row['status'], 'expires_at': row.get('expires_at'),
            'summary': summary, 'proposal': row}


def propose(client, user, kind, day, scoring_period_id, add_player_id, drop_player_id, counterparty_team_id,
            give_player_ids, receive_player_ids):
    given = {'date': day, 'scoring_period_id': scoring_period_id, 'add_player_id': add_player_id,
             'drop_player_id': drop_player_id, 'counterparty_team_id': counterparty_team_id,
             'give_player_ids': give_player_ids, 'receive_player_ids': receive_player_ids}
    allowed = {'lineup': {'date', 'scoring_period_id'}, 'roster_edit': {'add_player_id', 'drop_player_id'},
               'trade': {'counterparty_team_id', 'give_player_ids', 'receive_player_ids'}}[kind]
    extra = sorted(name for name, value in given.items() if value is not None and name not in allowed)
    if extra:
        raise ToolError(f"{', '.join(extra)} do not apply to kind='{kind}'. It takes {', '.join(sorted(allowed))}.")
    account, espn = espn_account(client, user)
    if kind == 'lineup':
        if day is not None and scoring_period_id is not None:
            raise ToolError('Pass date or scoring_period_id, not both (neither means today).')
        run = espn_call(lineup.run_lineup, client, account, espn, dry_run=True, scoring_period_id=scoring_period_id,
                        date=day, scoreboard=ScoreboardClient())
        if run['status'] == 'auth_error':
            raise ToolError(RELINK_STEP)
        if run['status'] != 'dry_run' or not run.get('id'):
            raise ToolError(f"Could not plan the lineup: {run.get('error') or run['status']}. Nothing was submitted.")
        row = proposal_view(kind, run)
    elif kind == 'roster_edit':
        row = proposal_view(kind, espn_call(roster_edits.propose_edit, client, account, espn,
                                            add_player_id=add_player_id, drop_player_id=drop_player_id))
    else:
        if counterparty_team_id is None or not give_player_ids or not receive_player_ids:
            raise ToolError('A trade needs counterparty_team_id, give_player_ids and receive_player_ids.')
        row = proposal_view(kind, espn_call(trades.propose_trade, client, account, espn,
                                            counterparty_team_id=counterparty_team_id,
                                            give_player_ids=give_player_ids, receive_player_ids=receive_player_ids))
    return {**row, 'next_step': 'Nothing was sent to ESPN. Show the user the summary; if they approve, call '
                                f"approve_fantasy_change(kind='{kind}', proposal_id='{row['proposal_id']}', "
                                'idempotency_key=...) to preview, then again with dry_run=false.'}


def approvable(client, account, kind, proposal_id):
    """The caller's pending, unexpired proposal. Reads only our tables; nothing is sent."""
    row = stored(client, account, None, kind, proposal_id)
    if row is None:
        raise not_found(kind, proposal_id)
    activity_kind = next(name for name, value in ACTIVITY.items() if value == kind)
    if kind == 'lineup':
        if row.get('mode') != 'dry_run' or row.get('status') != 'dry_run' or row.get('scoring_period_id') is None:
            raise ToolError(f'Lineup run {proposal_id} is not a lineup preview. Call '
                            "propose_fantasy_change(kind='lineup') for one.")
        if expired(row.get('created_at'), LINEUP_TTL_MINUTES):
            raise ToolError(f"Lineup preview {proposal_id} is older than {LINEUP_TTL_MINUTES} minutes. Call "
                            "propose_fantasy_change(kind='lineup') again for a current plan.")
        return row
    if row['status'] in write_safety.UNRESOLVED:
        raise ToolError(f'{KIND_NAMES[kind].capitalize()} {proposal_id} is {row["status"]}: ESPN may already have '
                        f"it. Call get_fantasy_activity(kind='{activity_kind}', proposal_id='{proposal_id}') to "
                        'reconcile it from ESPN; never approve it again.')
    if row['status'] != 'pending':
        raise ToolError(f'{KIND_NAMES[kind].capitalize()} {proposal_id} is already {row["status"]}. Propose a new '
                        'change instead.')
    if expired(row.get('expires_at'), 0):
        raise ToolError(f'{KIND_NAMES[kind].capitalize()} {proposal_id} expired at {row["expires_at"]}. Propose it '
                        'again to re-validate it against the live league.')
    return row


def receipt(client, user, key):
    rows = (client.table(RECEIPTS).select('payload,target,result')
            .eq('user_id', user.id).eq('idempotency_key', key).execute().data)
    return rows[0] if rows else None


def record(client, user, key, result):
    (client.table(RECEIPTS).update({'result': result})
     .eq('user_id', user.id).eq('idempotency_key', key).is_('result', 'null').execute())


def outcome(kind, row, summary, **extra):
    result = {'dry_run': False, 'kind': kind, 'proposal_id': row['id'], 'status': row['status'],
              'error': row.get('error'), 'summary': f"{KIND_NAMES[kind].capitalize()} {row['status']}: {summary}",
              'proposal': row, **extra}
    if row['status'] == 'waiver_pending':
        result['note'] = 'ESPN filed the add as a waiver claim (bid 0); it processes when waivers run.'
    if row['status'] == 'offered':
        result['note'] = 'The counterparty accepts or declines on ESPN; that is not tracked here.'
    return result


def not_sent(client, user, key, kind, proposal_id, reason):
    """Record that this key never reached ESPN, so a replay repeats the refusal instead of approving."""
    message = (f'{reason} Nothing was sent to ESPN under this idempotency_key, and the key is spent: approve again '
               'with a new key once that is resolved.')
    record(client, user, key, {'dry_run': False, 'kind': kind, 'proposal_id': proposal_id, 'status': 'not_sent',
                               'summary': message})
    raise ToolError(message)


def finish(client, user, key, kind, row, summary, error=None, **extra):
    """Turn the stored edit or trade state after an approval attempt into a recorded result, or keep the key open."""
    if row['status'] in DONE:
        result = outcome(kind, row, summary, **extra)
        if isinstance(error, EspnAuthError):
            result['next_step'] = RELINK_STEP
        record(client, user, key, result)
        return result
    if row['status'] in write_safety.UNRESOLVED:
        raise ToolError(UNSETTLED.format(what=KIND_NAMES[kind], detail=f"it is {row['status']}"))
    # Still pending: the approval never claimed it, so it never reached ESPN.
    not_sent(client, user, key, kind, row['id'], f'{error or "The approval did not start"}.')


def settle(client, user, account, espn, key, found):
    """Settle a key whose outcome was not recorded, by reading ESPN only.

    The request that wrote the receipt may still be running, so this never submits.
    """
    payload, target = found['payload'], found['target']
    kind, proposal_id = payload['kind'], payload['proposal_id']
    if kind == 'lineup':
        period = target['scoring_period_id']
        fresh = espn_call(lineup.run_lineup, client, account, espn, dry_run=True, scoring_period_id=period,
                          scoreboard=ScoreboardClient())
        if fresh['status'] == 'auth_error':
            raise ToolError(RELINK_STEP)
        remaining = lineup_moves(fresh.get('plan') or {}) if fresh['status'] == 'dry_run' else None
        if remaining is None:
            raise ToolError(UNSETTLED.format(what='lineup', detail=fresh.get('error') or fresh['status']))
        if remaining:
            raise ToolError(UNSETTLED_LINEUP.format(count=len(remaining), period=period))
        result = {'dry_run': False, 'kind': kind, 'proposal_id': proposal_id, 'status': 'set',
                  'summary': f'Lineup set for scoring period {period}: ESPN shows every scheduled player placed.',
                  'run': fresh, 'confirmed_from': 'your ESPN lineup'}
        record(client, user, key, result)
        return result
    row = espn_call(stored, client, account, espn, kind, proposal_id)
    if row is None:  # the account was deleted and re-onboarded since
        raise not_found(kind, proposal_id)
    if row['status'] == 'pending' and not expired(row.get('expires_at'), 0):
        # The first request reserved the key and has not claimed the proposal yet.
        raise ToolError(UNSETTLED.format(what=KIND_NAMES[kind], detail='the approval has not started yet'))
    if row['status'] == 'pending':
        not_sent(client, user, key, kind, proposal_id, f'{KIND_NAMES[kind].capitalize()} {proposal_id} expired '
                 'before it was approved. Propose it again.')
    return finish(client, user, key, kind, row, target['summary'], confirmed_from='ESPN')


def replay(client, user, account, espn, key, found, fingerprint):
    if found['payload'] != fingerprint:
        if found['result'] is None:
            raise ToolError('This idempotency_key belongs to an earlier, unconfirmed approval of another change. '
                            'Repeat that approval with its original kind and proposal_id and this key to settle it, '
                            'before approving anything else.')
        raise ToolError('This idempotency_key was already used for: ' + found['result']['summary']
                        + ' A different approval needs its own key.')
    if found['result'] is not None:
        if found['result']['status'] == 'not_sent':
            raise ToolError(found['result']['summary'])
        return found['result']
    return settle(client, user, account, espn, key, found)


def claim_lineup(client, user, key, proposal_id):
    """Claim a lineup proposal for this key. Returns None, or the approval that claimed it first.

    A lineup proposal is an append-only dry-run row with no status to claim, so the
    claim is its own row: one per proposal, never released, whatever the key.
    """
    claimed = (client.table(LINEUP_APPROVALS).upsert(
        {'proposal_id': proposal_id, 'user_id': user.id, 'idempotency_key': key},
        on_conflict='proposal_id', ignore_duplicates=True).execute().data)
    if claimed:
        return None
    return (client.table(LINEUP_APPROVALS).select('user_id,idempotency_key')
            .eq('proposal_id', proposal_id).execute().data)[0]


def approved_earlier(client, user, account, espn, key, first):
    """Answer a second key for a lineup proposal another key claimed: replay or reread, never submit."""
    rows = (client.table(RECEIPTS).select('result').eq('user_id', first['user_id'])
            .eq('idempotency_key', first['idempotency_key']).execute().data)
    if rows and rows[0]['result'] is not None:
        record(client, user, key, rows[0]['result'])
        return rows[0]['result']
    # The first approval may still be running: settle this key from the ESPN lineup alone.
    return settle(client, user, account, espn, key, receipt(client, user, key))


def send(client, account, espn, kind, row):
    """The one approval that may reach ESPN. Its proposal is claimed atomically first: here for a lineup,
    by the existing gates for an edit or trade."""
    if kind == 'lineup':
        return lineup.run_lineup(client, account, espn, dry_run=False, scoring_period_id=row['scoring_period_id'],
                                 scoreboard=ScoreboardClient())
    if kind == 'roster_edit':
        return roster_edits.approve_edit(client, account, espn, row['id'], scoreboard=ScoreboardClient())
    return trades.approve_trade(client, account, espn, row['id'], scoreboard=ScoreboardClient())


def approve(client, user, kind, proposal_id, key, dry_run):
    account, espn = espn_account(client, user)
    fingerprint = {'kind': kind, 'account_id': account['id'], 'proposal_id': proposal_id}
    if not dry_run and (found := receipt(client, user, key)):
        return replay(client, user, account, espn, key, found, fingerprint)
    row = approvable(client, account, kind, proposal_id)
    summary = describe(kind, row)
    if dry_run:
        return {'dry_run': True, 'status': 'would_approve', 'kind': kind, 'proposal_id': proposal_id,
                'summary': summary, 'proposal': row,
                'next_step': 'Nothing was sent. Show the user the summary; if they confirm, call '
                             'approve_fantasy_change again with the same arguments and dry_run=false.'}
    target = {'summary': summary, 'scoring_period_id': row.get('scoring_period_id')}
    reserved = (client.table(RECEIPTS).upsert(
        {'user_id': user.id, 'idempotency_key': key, 'payload': fingerprint, 'target': target},
        on_conflict='user_id,idempotency_key', ignore_duplicates=True).execute().data)
    if not reserved:
        return replay(client, user, account, espn, key, receipt(client, user, key), fingerprint)
    if kind == 'lineup' and (first := claim_lineup(client, user, key, proposal_id)):
        return approved_earlier(client, user, account, espn, key, first)
    try:
        answer, error = send(client, account, espn, kind, row), None
    except Exception as failure:
        logger.warning('ESPN %s approval raised: %s', kind, type(failure).__name__)
        answer, error = None, failure
    if kind == 'lineup':
        if answer is None:
            raise ToolError(UNCONFIRMED.format(what='lineup')) from error
        result = {'dry_run': False, 'kind': kind, 'proposal_id': proposal_id, 'status': answer['status'],
                  'error': answer.get('error'), 'summary': f"Lineup run {answer['status']}: {lineup_summary(answer)}",
                  'run': answer}
        if answer['status'] == 'auth_error':
            result['next_step'] = RELINK_STEP
        record(client, user, key, result)
        return result
    try:
        current = stored(client, account, None, kind, proposal_id)
    except Exception as failure:
        raise ToolError(UNCONFIRMED.format(what=KIND_NAMES[kind])) from failure
    if current is None:
        raise ToolError(UNCONFIRMED.format(what=KIND_NAMES[kind])) from error
    return finish(client, user, key, kind, current, summary, error)


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
        result, account = accounts.link_account_to_owner(client, api_token, user.id)
    except AccountError as error:
        raise ToolError('No ESPN account matches that token. Use the cce_ token from your ESPN onboarding '
                        f'exactly as shown, or onboard again at POST {ONBOARD_URL}.') from error
    if result == 'other_owner':
        raise ToolError('This ESPN account is linked to another Commons user. Sign in as that user, '
                        f'or onboard your own ESPN cookies at POST {ONBOARD_URL}.')
    if result not in {'linked', 'already_linked'}:
        raise ToolError('Could not link the account. Retry in a moment; nothing changed.')
    linked_result = {'linked': True, 'status': result, 'account': {'id': account['id'], 'label': account['label']},
                     'next_step': "Call get_fantasy_league(view='league')."}
    if result == 'linked' and previous and previous['id'] != account['id']:
        linked_result['replaced_account'] = {'id': previous['id'], 'label': previous['label']}
    return linked_result


def register_tools(mcp, context):
    async def invoke(scope, operation, *args):
        access = context.need_scope(scope)
        user = await context.signed_in_user(access)
        try:
            return await run_in_threadpool(operation, context.service_client, user, *args)
        except ToolError:
            raise
        except Exception as error:
            logger.warning('ESPN connector call failed: %s', type(error).__name__)
            raise ToolError('The ESPN request failed. Retry in a moment with the same arguments.') from error

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def get_fantasy_league(view: Literal['league', 'standings', 'team', 'draft', 'transactions'] = 'league',
                                 team_id: Id | None = None, limit: Limit = 25) -> dict:
        """Read your ESPN fantasy basketball league.

        view: league (settings, teams and your_team_id), standings, team (one team's
        roster; team_id defaults to your own team), draft, or transactions (newest
        first, up to limit).
        """
        return await invoke(READ_SCOPE, league, view, team_id, limit)

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def get_fantasy_trends(kind: Literal['players', 'teams'] = 'players', limit: Limit = 10) -> dict:
        """Player ownership and performance trends (kind='players', top limit) or per-team trends: weekly
        points, last-3 average, all-play wins and luck (kind='teams')."""
        return await invoke(READ_SCOPE, trends, kind, limit)

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def get_fantasy_activity(kind: Literal['lineup_runs', 'roster_edits', 'trades'],
                                   proposal_id: ProposalId | None = None, limit: Limit = 25,
                                   scoring_period_id: Period | None = None) -> dict:
        """Your lineup runs, roster edits or trade proposals, newest first.

        Pass proposal_id for one item; an edit or trade whose ESPN outcome is unresolved
        is reconciled by rereading ESPN, never resubmitted. scoring_period_id narrows
        lineup_runs to one day.
        """
        return await invoke(READ_SCOPE, activity, kind, proposal_id, limit, scoring_period_id)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False,
                           'openWorldHint': True})
    async def propose_fantasy_change(kind: Kind, date: Date | None = None, scoring_period_id: Period | None = None,
                                     add_player_id: Id | None = None, drop_player_id: Id | None = None,
                                     counterparty_team_id: Id | None = None, give_player_ids: Players | None = None,
                                     receive_player_ids: Players | None = None) -> dict:
        """Propose a change to your own team. SENDS NOTHING to ESPN; it returns a summary and a proposal_id.

        kind='lineup': plan one day's lineup (date YYYY-MM-DD or scoring_period_id;
        neither means today) under the standing rule that every scheduled player starts.
        kind='roster_edit': add_player_id and/or drop_player_id (a swap is both).
        kind='trade': counterparty_team_id, give_player_ids and receive_player_ids.
        The change is validated against the live league and expires in 30 minutes.
        Show the user the summary, then use approve_fantasy_change.
        """
        return await invoke(EDIT_SCOPE, propose, kind, date.isoformat() if date else None, scoring_period_id,
                            add_player_id, drop_player_id, counterparty_team_id, give_player_ids,
                            receive_player_ids)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': True,
                           'openWorldHint': True})
    async def approve_fantasy_change(kind: Kind, proposal_id: ProposalId, idempotency_key: Key,
                                     dry_run: DryRun = True) -> dict:
        """Preview, then submit one proposal from propose_fantasy_change to ESPN.

        dry_run=true (the default) shows what approving submits and sends nothing. After
        the user explicitly approves that exact change, call again with dry_run=false.
        A roster edit adds/drops for real (a waiver target becomes a claim); a trade
        sends a real offer the other manager sees. Retry with the same idempotency_key
        after any error: it rereads ESPN and never submits twice.
        """
        return await invoke(EDIT_SCOPE, approve, kind, proposal_id, idempotency_key, dry_run)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': False})
    async def link_espn_account(api_token: str) -> dict:
        """Link your ESPN account to your Commons sign-in once, using its existing cce_ token.

        The token proves ownership; it is checked against its stored hash and never
        stored or returned. Afterwards the ESPN tools need no token. Linking a different
        account of yours replaces the earlier link; an account linked to another Commons
        user is refused.
        """
        return await invoke(EDIT_SCOPE, link, api_token)


provider = ToolProvider(
    'espn', register_tools,
    {'get_fantasy_league': 'read', 'get_fantasy_trends': 'read', 'get_fantasy_activity': 'read',
     'propose_fantasy_change': 'edit', 'approve_fantasy_change': 'edit', 'link_espn_account': 'edit'},
    title='ESPN', description='Read your ESPN fantasy basketball league; propose and approve lineups, '
                              'roster edits and trades.',
    url=DOCS_URL, status=status,
    link=AccountLink(LINK_STEP, linked=linked, tool='link_espn_account', url=ONBOARD_URL))
