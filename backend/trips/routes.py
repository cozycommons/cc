"""Supabase-authenticated HTTP commands shared by people and agents."""
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from postgrest.exceptions import APIError

from dice.routes import ADMIN_EMAILS

from .ledger import (CREATES, LedgerError, apply_command, balances, claim_invite, deleted_expense, invite_slot,
                     new_group, require_member)
from .imports import ImportTrip, prepare_import, require_same_import
from .matching import candidates_for, read_accounts, suggest
from .profiles import current_profile, render_group, render_groups
from .venmo import normalize_username

router = APIRouter(tags=['Cozy Trips'])
bearer = HTTPBearer(auto_error=False)
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Money = Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]
Share = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
Currency = Literal['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'MXN']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateTrip(Input):
    id: UUID
    name: Name
    currency: Currency = 'USD'
    display_name: Name | None = None


class Revision(Input):
    revision: Annotated[int, Field(strict=True, ge=1)]


class AddMember(Revision):
    name: Name


class Rename(Revision):
    name: Name


class JoinTrip(Input):
    invite_token: Annotated[str, StringConstraints(min_length=40, max_length=100)]


class Expense(Revision):
    id: UUID
    description: Name
    amount_minor: Money
    paid_by: UUID
    split_mode: Literal['equal', 'exact', 'shares', 'percent'] = 'equal'
    participants: Annotated[list[UUID], Field(min_length=1, max_length=30)]
    shares: dict[UUID, Share] = Field(default_factory=dict)
    # Several people paying: amount each paid, adding up to the expense. Empty means paid_by paid it all.
    payers: dict[UUID, Share] = Field(default_factory=dict)
    date: date
    category: Literal['food', 'stay', 'transport', 'activities', 'other'] = 'other'
    notes: Annotated[str, StringConstraints(max_length=1000)] = ''


class VenmoUsername(Input):
    venmo_username: Annotated[str, StringConstraints(max_length=200)] | None = None

    @field_validator('venmo_username')
    @classmethod
    def valid_username(cls, value):
        return normalize_username(value)


class MemberVenmo(Revision, VenmoUsername):
    pass


class MemberAccount(Revision):
    user_id: UUID


class Repayment(Revision):
    id: UUID
    from_member: UUID
    to_member: UUID
    amount_minor: Money
    date: date
    notes: Annotated[str, StringConstraints(max_length=1000)] = ''


def client(request):
    return request.app.state.trips_supabase


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, 'Sign in to use Cozy Trips.')
    try:
        user = client(request).auth.get_user(credentials.credentials).user
    except AuthApiError:
        raise HTTPException(401, 'Your session expired. Please sign in again.')
    if not user:
        raise HTTPException(401, 'Sign in to use Cozy Trips.')
    return user


def is_admin(user):
    """The Commons admins Dice already trusts, and only with a verified email."""
    return bool(user.email and user.email_confirmed_at and user.email.lower() in ADMIN_EMAILS)


def my_profile(request, user):
    return {**current_profile(client(request), user), 'is_admin': is_admin(user)}


def require_admin(user):
    if not is_admin(user):
        raise HTTPException(403, 'Only Cozy Commons admins can link people to accounts.')


def read_row(request, trip_id):
    rows = client(request).table('trips_groups').select('*').eq('id', str(trip_id)).execute().data
    if not rows:
        raise LedgerError('Trip not found or you are not a member.', 404)
    return rows[0]


def save_revision(request, before, after):
    rows = (client(request).table('trips_groups')
            .update({key: after[key] for key in ['data', 'member_user_ids', 'revision', 'updated_at']})
            .eq('id', before['id']).eq('revision', before['revision']).execute().data)
    if not rows:
        raise LedgerError('Someone changed this trip. Refresh, review the changes, and try again.', 409)
    return render_group(client(request), rows[0])


RETRYABLE = {'add_expense': 'expenses', 'add_repayment': 'repayments'}
AUDIT_FIELDS = {'created_at', 'created_by', 'updated_at', 'updated_by'}


def already_saved(row, user_id, kind, payload):
    """A retried create whose first response was lost returns the saved trip instead of a conflict.

    Replaying the retry must produce exactly the saved record (split, shares, notes and all); anything else conflicts."""
    collection = RETRYABLE.get(kind)
    saved = next((item for item in row['data'][collection] if item['id'] == payload['id']), None) if collection else None
    if saved is None:
        return False
    trial = deepcopy(row)
    trial['data'][collection] = [item for item in trial['data'][collection] if item['id'] != payload['id']]
    replay, _ = apply_command(trial, user_id, kind, {**payload, 'revision': row['revision']})
    candidate = next(item for item in replay['data'][collection] if item['id'] == payload['id'])
    if {k: v for k, v in candidate.items() if k not in AUDIT_FIELDS} == {k: v for k, v in saved.items() if k not in AUDIT_FIELDS}:
        return True
    raise LedgerError('This item was already saved with different details. Refresh to see it.', 409)


def already_restored(row, expense_id):
    """True only when the expense now on the trip is the deleted version; a different record with that ID conflicts."""
    current = next((e for e in row['data']['expenses'] if e['id'] == expense_id), None)
    if current is None:
        return False
    snapshot = deleted_expense(row['data'], expense_id)
    ignored = {'updated_at', 'updated_by'}
    if snapshot and {k: v for k, v in current.items() if k not in ignored} == {k: v for k, v in snapshot.items() if k not in ignored}:
        return True
    raise LedgerError('A different expense is already saved with this ID. Refresh to see it.', 409)


def command(request, trip_id, user, kind, payload):
    # Creates are independent of other changes: when another write lands first, reread and add on top of it.
    attempts = 5 if kind in CREATES else 1
    try:
        for attempt in range(attempts):
            before = read_row(request, trip_id)
            require_member(before, user.id)
            if already_saved(before, user.id, kind, payload):
                return render_group(client(request), before)
            if kind == 'restore_expense' and already_restored(before, payload['id']):
                return render_group(client(request), before)  # A retried restore whose first response was lost.
            after, invitation = apply_command(before, user.id, kind, payload)
            try:
                group = save_revision(request, before, after)
            except LedgerError as error:
                if error.status == 409 and attempt + 1 < attempts:
                    continue
                raise
            return {'group': group, 'invite_token': invitation} if invitation else group
    except LedgerError as error:
        raise HTTPException(error.status, str(error))


def imported_trip(request, payload, user, save=False):
    try:
        row, report = prepare_import(payload.snapshot, user.id, payload.own_member_id)
        existing = client(request).table('trips_groups').select('*').eq('id', row['id']).execute().data
        if existing:
            require_same_import(existing[0], row)
            return {'group': render_group(client(request), existing[0]), 'report': report, 'status': 'existing'}
        if not save:
            return {'group': render_group(client(request), row), 'report': report, 'status': 'preview'}
        try:
            saved = client(request).table('trips_groups').insert(row).execute().data[0]
        except APIError as error:
            if error.code != '23505':
                raise
            # A concurrent identical import or a lost response must not duplicate the trip.
            saved = read_row(request, row['id'])
            require_same_import(saved, row)
            return {'group': render_group(client(request), saved), 'report': report, 'status': 'existing'}
        return {'group': render_group(client(request), saved), 'report': report, 'status': 'created'}
    except LedgerError as error:
        raise HTTPException(error.status, str(error))


@router.post('/imports/preview')
def preview_import(payload: ImportTrip, request: Request, user=Depends(current_user)):
    return imported_trip(request, payload, user)


@router.post('/imports')
def save_import(payload: ImportTrip, request: Request, user=Depends(current_user)):
    return imported_trip(request, payload, user, save=True)


@router.get('/groups')
def list_trips(request: Request, user=Depends(current_user)):
    rows = (client(request).table('trips_groups').select('*')
            .contains('member_user_ids', [user.id]).order('updated_at', desc=True).execute().data)
    return render_groups(client(request), rows)


@router.get('/me')
def get_my_profile(request: Request, user=Depends(current_user)):
    return my_profile(request, user)


@router.put('/me')
def update_my_profile(payload: VenmoUsername, request: Request, user=Depends(current_user)):
    # Only the caller's own account is writable. GoTrue merges these keys into existing metadata.
    username = payload.venmo_username
    provenance = {'source': 'self', 'provided_by_user_id': user.id,
                  'provided_at': datetime.now(timezone.utc).isoformat(), 'owner_confirmed': True} if username else None
    if username:
        from venmo.profiles import lookup
        try:
            preview = lookup.load(client(request), username.lower()) or {}
        except Exception:
            preview = {}
        if preview.get('found'):
            provenance['display_name'] = preview['displayName']
    try:
        updated = client(request).auth.admin.update_user_by_id(
            user.id, {'user_metadata': {'venmo_username': username, 'venmo_username_provenance': provenance}}).user
    except AuthApiError:
        raise HTTPException(503, 'Could not save your Venmo username. Try again.')
    if not updated or updated.id != user.id:
        raise HTTPException(503, 'Could not confirm your Venmo username was saved. Reload to check.')
    return my_profile(request, updated)


@router.post('/groups', status_code=201)
def create_trip(payload: CreateTrip, request: Request, user=Depends(current_user)):
    existing = client(request).table('trips_groups').select('*').eq('id', str(payload.id)).execute().data
    if existing:
        row = existing[0]
        if row['owner_id'] != user.id:
            raise HTTPException(409, 'Choose a new trip ID.')
        return render_group(client(request), row)
    display_name = payload.display_name or current_profile(client(request), user)['display_name']
    row = new_group(str(payload.id), user.id, payload.name, payload.currency, display_name)
    try:
        saved = client(request).table('trips_groups').insert(row).execute().data[0]
    except APIError as error:
        if error.code != '23505':
            raise
        # A lost response or concurrent retry must reopen, never overwrite, this ID.
        saved = read_row(request, payload.id)
        if saved['owner_id'] != user.id:
            raise HTTPException(409, 'Choose a new trip ID.')
    return render_group(client(request), saved)


@router.get('/groups/{trip_id}')
def get_trip(trip_id: UUID, request: Request, user=Depends(current_user)):
    try:
        row = read_row(request, trip_id)
        require_member(row, user.id)
        return render_group(client(request), row)
    except LedgerError as error:
        raise HTTPException(error.status, str(error))


@router.put('/groups/{trip_id}')
def rename_trip(trip_id: UUID, payload: Rename, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'rename_trip', payload.model_dump())


@router.delete('/groups/{trip_id}')
def delete_trip(trip_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    try:
        row = read_row(request, trip_id)
        require_member(row, user.id)
    except LedgerError as error:
        raise HTTPException(error.status, str(error))
    if row['owner_id'] != user.id:
        raise HTTPException(403, 'Only the trip creator can delete the trip.')
    if payload.revision != row['revision']:
        raise HTTPException(409, 'Someone changed this trip. Review the latest version before deleting it.')
    deleted = (client(request).table('trips_groups').delete()
               .eq('id', row['id']).eq('revision', row['revision']).execute().data)
    if not deleted:
        raise HTTPException(409, 'Someone changed this trip. Review the latest version before deleting it.')
    return {'deleted': row['id']}


@router.post('/groups/{trip_id}/invite-preview')
def preview_invite(trip_id: UUID, payload: JoinTrip, request: Request, user=Depends(current_user)):
    """What an invitation leads to, shown before joining. The one-use token is the only credential."""
    try:
        row = read_row(request, trip_id)
    except LedgerError:
        raise HTTPException(404, 'This invitation is invalid or has already been used.')
    if user.id in row['member_user_ids']:
        return {'already_member': True, 'trip_name': row['data']['name']}
    slot = invite_slot(row, payload.invite_token)
    if not slot or slot.get('user_id'):
        raise HTTPException(404, 'This invitation is invalid or has already been used.')
    group = render_group(client(request), row)
    owner = next((m for m in group['members'] if m.get('user_id') == row['owner_id']), None)
    return {'already_member': False, 'trip_name': row['data']['name'], 'currency': row['data']['currency'],
            'inviter': owner['display_name'] if owner else None, 'member_name': slot['name'],
            'member_count': len(row['data']['members']), 'balance_minor': balances(row['data'])[slot['id']]}


@router.post('/groups/{trip_id}/members', status_code=201)
def add_member(trip_id: UUID, payload: AddMember, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'add_member', payload.model_dump(mode='json'))


@router.post('/groups/{trip_id}/members/{member_id}/invite')
def invite_member(trip_id: UUID, member_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'invite_member', {**payload.model_dump(), 'member_id': str(member_id)})


@router.put('/groups/{trip_id}/members/{member_id}')
def rename_member(trip_id: UUID, member_id: UUID, payload: Rename, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'rename_member', {**payload.model_dump(), 'member_id': str(member_id)})


@router.delete('/groups/{trip_id}/members/{member_id}')
def remove_member(trip_id: UUID, member_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'remove_member', {**payload.model_dump(), 'member_id': str(member_id)})


@router.put('/groups/{trip_id}/members/{member_id}/venmo')
def set_member_venmo(trip_id: UUID, member_id: UUID, payload: MemberVenmo, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'set_member_venmo', {**payload.model_dump(), 'member_id': str(member_id)})


@router.post('/groups/{trip_id}/members/{member_id}/link')
def link_member(trip_id: UUID, member_id: UUID, payload: MemberAccount, request: Request, user=Depends(current_user)):
    # Admin and creator: an ordinary creator could otherwise enrol any account and read its profile.
    require_admin(user)
    # Authorize the trip before looking at any account, so outsiders learn nothing from the answers.
    try:
        row = read_row(request, trip_id)
        require_member(row, user.id)
        if row['owner_id'] != user.id:
            raise LedgerError('Only the trip creator can link people to accounts.', 403)
    except LedgerError as error:
        raise HTTPException(error.status, str(error))
    try:
        account = client(request).auth.admin.get_user_by_id(str(payload.user_id)).user
    except AuthApiError as error:
        if error.status != 404:
            raise HTTPException(503, 'Could not check that account. Try again.')
        account = None
    if not account or account.id != str(payload.user_id):
        raise HTTPException(404, 'No Commons account has that ID.')
    blocked = link_blocked(request, row, str(member_id), str(payload.user_id))
    if blocked:
        raise HTTPException(422, blocked)
    return command(request, trip_id, user, 'link_member', {**payload.model_dump(mode='json'), 'member_id': str(member_id)})


def link_blocked(request, row, member_id, user_id):
    """Only an account the review screen would offer, and could tell apart, may be linked; never one posted blind."""
    member = next((m for m in row['data']['members'] if m['id'] == member_id and not m.get('user_id')), None)
    if not member:
        return None  # The link command reports a missing or already linked place itself.
    candidate = next((c for c in candidates_for(member, row['data']['members'], read_accounts(client(request)))
                      if c['user_id'] == user_id), None)
    if not candidate:
        return 'That account isn’t a likely match for this person. Send them an invite link instead.'
    if candidate['lookalike']:
        return 'That account can’t be told apart from another one. Send this person an invite link instead.'
    return None


@router.post('/groups/{trip_id}/members/{member_id}/unlink')
def unlink_member(trip_id: UUID, member_id: UUID, payload: MemberAccount, request: Request, user=Depends(current_user)):
    require_admin(user)
    return command(request, trip_id, user, 'unlink_member', {**payload.model_dump(mode='json'), 'member_id': str(member_id)})


@router.get('/admin/groups/{trip_id}/link-suggestions')
def link_suggestions(trip_id: UUID, request: Request, response: Response, user=Depends(current_user)):
    """Read-only name-match suggestions for the creator to review one by one. Never stored or cached."""
    require_admin(user)
    try:
        row = read_row(request, trip_id)
        require_member(row, user.id)
        if row['owner_id'] != user.id:
            raise LedgerError('Only the trip creator can review account links.', 403)
    except LedgerError as error:
        raise HTTPException(error.status, str(error))
    response.headers['Cache-Control'] = 'no-store'
    # Links confirm against this revision, so a trip changed since the review conflicts instead of linking.
    return {'revision': row['revision'], 'members': suggest(row['data']['members'], read_accounts(client(request)))}


@router.post('/groups/{trip_id}/join')
def join_trip(trip_id: UUID, payload: JoinTrip, request: Request, user=Depends(current_user)):
    try:
        before = read_row(request, trip_id)
        if user.id in before['member_user_ids']:
            # Reopening/retrying an invitation must not claim a second place.
            return render_group(client(request), before)
        after = claim_invite(before, user.id, payload.invite_token)
        return save_revision(request, before, after)
    except LedgerError as error:
        raise HTTPException(error.status, str(error))


@router.post('/groups/{trip_id}/expenses', status_code=201)
def add_expense(trip_id: UUID, payload: Expense, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'add_expense', payload.model_dump(mode='json'))


@router.put('/groups/{trip_id}/expenses/{expense_id}')
def edit_expense(trip_id: UUID, expense_id: UUID, payload: Expense, request: Request, user=Depends(current_user)):
    if expense_id != payload.id:
        raise HTTPException(400, 'Expense IDs must match.')
    return command(request, trip_id, user, 'edit_expense', payload.model_dump(mode='json'))


@router.delete('/groups/{trip_id}/expenses/{expense_id}')
def delete_expense(trip_id: UUID, expense_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'delete_expense', {**payload.model_dump(), 'id': str(expense_id)})


@router.post('/groups/{trip_id}/expenses/{expense_id}/restore', status_code=201)
def restore_expense(trip_id: UUID, expense_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'restore_expense', {**payload.model_dump(), 'id': str(expense_id)})


@router.post('/groups/{trip_id}/repayments', status_code=201)
def add_repayment(trip_id: UUID, payload: Repayment, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'add_repayment', payload.model_dump(mode='json'))


@router.delete('/groups/{trip_id}/repayments/{repayment_id}')
def delete_repayment(trip_id: UUID, repayment_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'delete_repayment', {**payload.model_dump(), 'id': str(repayment_id)})
