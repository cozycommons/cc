"""Supabase-authenticated HTTP commands shared by people and agents."""
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .ledger import LedgerError, apply_command, claim_invite, new_group, public_group, require_member

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
    display_name: Name


class Revision(Input):
    revision: Annotated[int, Field(strict=True, ge=1)]


class AddMember(Revision):
    name: Name


class JoinTrip(Input):
    invite_token: Annotated[str, StringConstraints(min_length=40, max_length=100)]


class Expense(Revision):
    id: UUID
    description: Name
    amount_minor: Money
    paid_by: UUID
    split_mode: Literal['equal', 'exact'] = 'equal'
    participants: Annotated[list[UUID], Field(min_length=1, max_length=30)]
    shares: dict[UUID, Share] = Field(default_factory=dict)
    date: date
    category: Literal['food', 'stay', 'transport', 'activities', 'other'] = 'other'
    notes: Annotated[str, StringConstraints(max_length=1000)] = ''


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
    return public_group(rows[0])


def command(request, trip_id, user, kind, payload):
    try:
        before = read_row(request, trip_id)
        after, invitation = apply_command(before, user.id, kind, payload)
        group = save_revision(request, before, after)
        return {'group': group, 'invite_token': invitation} if invitation else group
    except LedgerError as error:
        raise HTTPException(error.status, str(error))


@router.get('/groups')
def list_trips(request: Request, user=Depends(current_user)):
    rows = (client(request).table('trips_groups').select('*')
            .contains('member_user_ids', [user.id]).order('updated_at', desc=True).execute().data)
    return [public_group(row) for row in rows]


@router.post('/groups', status_code=201)
def create_trip(payload: CreateTrip, request: Request, user=Depends(current_user)):
    existing = client(request).table('trips_groups').select('*').eq('id', str(payload.id)).execute().data
    if existing:
        row = existing[0]
        if row['owner_id'] != user.id:
            raise HTTPException(409, 'Choose a new trip ID.')
        return public_group(row)
    row = new_group(str(payload.id), user.id, payload.name, payload.currency, payload.display_name)
    rows = client(request).table('trips_groups').insert(row).execute().data
    return public_group(rows[0])


@router.get('/groups/{trip_id}')
def get_trip(trip_id: UUID, request: Request, user=Depends(current_user)):
    try:
        row = read_row(request, trip_id)
        require_member(row, user.id)
        return public_group(row)
    except LedgerError as error:
        raise HTTPException(error.status, str(error))


@router.post('/groups/{trip_id}/members', status_code=201)
def add_member(trip_id: UUID, payload: AddMember, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'add_member', payload.model_dump(mode='json'))


@router.post('/groups/{trip_id}/members/{member_id}/invite')
def invite_member(trip_id: UUID, member_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'invite_member', {**payload.model_dump(), 'member_id': str(member_id)})


@router.post('/groups/{trip_id}/join')
def join_trip(trip_id: UUID, payload: JoinTrip, request: Request, user=Depends(current_user)):
    try:
        before = read_row(request, trip_id)
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


@router.post('/groups/{trip_id}/repayments', status_code=201)
def add_repayment(trip_id: UUID, payload: Repayment, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'add_repayment', payload.model_dump(mode='json'))


@router.delete('/groups/{trip_id}/repayments/{repayment_id}')
def delete_repayment(trip_id: UUID, repayment_id: UUID, payload: Revision, request: Request, user=Depends(current_user)):
    return command(request, trip_id, user, 'delete_repayment', {**payload.model_dump(), 'id': str(repayment_id)})
