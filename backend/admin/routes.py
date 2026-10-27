from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, model_validator
from commons_roles import role_rpc, user_role

from .query import execute_query, reader_url

router = APIRouter()
security = HTTPBearer(auto_error=False)
PROJECTS = ['commons', 'dice', 'trips', 'crowdset', 'fantasy']


def require_admin(request: Request, response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    response.headers['Cache-Control'] = 'private, no-store'
    if not credentials:
        raise HTTPException(401, 'Sign in to continue.')
    try:
        user = request.app.state.analytics_supabase.auth.get_user(credentials.credentials).user
    except Exception:
        raise HTTPException(401, 'Invalid authentication token.')
    if not user or not user.email_confirmed_at or getattr(user, 'is_anonymous', False) or user_role(request.app.state.analytics_supabase, user.id) != 'admin':
        raise HTTPException(403, 'Access denied.')
    return user


class Filters(BaseModel):
    start_at: datetime
    end_at: datetime
    project: Literal['commons', 'dice', 'trips', 'crowdset', 'fantasy'] | None = None

    @model_validator(mode='after')
    def check_range(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError('Use timezone-aware dates.')
        seconds = (self.end_at - self.start_at).total_seconds()
        if not 0 < seconds <= 366 * 86400:
            raise ValueError('Choose a range of at most 366 days.')
        return self


class RunQuery(Filters):
    sql: str = Field(min_length=1, max_length=20000)


class Chart(BaseModel):
    type: Literal['table', 'line', 'bar'] = 'table'
    x: str = ''
    y: list[str] = Field(default_factory=list, max_length=10)
    series: str = ''


class SavedQuery(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=20000)
    visualization: Chart = Field(default_factory=Chart)
    position: int = Field(default=0, ge=0, le=10000)
    revision: int = Field(default=1, ge=1)


def store(request):
    return request.app.state.analytics_supabase.table('analytics_saved_queries')


@router.get('/session')
def session(user=Depends(require_admin)):
    return {'id': user.id, 'email': user.email}


@router.get('/catalog')
def catalog(request: Request, user=Depends(require_admin)):
    import psycopg
    from .query import VIEWS
    try:
        with psycopg.connect(reader_url(request.app.state.runtime_policy), connect_timeout=3) as conn:
            rows = conn.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'analytics' ORDER BY table_name, ordinal_position").fetchall()
        first = request.app.state.analytics_supabase.table('analytics_events').select('created_at').eq('schema_version', 1).order('created_at').limit(1).execute().data
        return {'collection_started_at': first[0]['created_at'] if first else None, 'projects': PROJECTS, 'views': [{'view': f'analytics.{view}', 'columns': [{'name': col, 'type': kind} for table, col, kind in rows if table == view]} for view in sorted(VIEWS)]}
    except psycopg.Error:
        raise HTTPException(503, 'Analytics connection unavailable.')


@router.get('/queries')
def list_queries(request: Request, user=Depends(require_admin)):
    return store(request).select('*').order('position').order('created_at').execute().data


@router.post('/queries', status_code=201)
def create_query(payload: SavedQuery, request: Request, user=Depends(require_admin)):
    from .query import validate_query
    validate_query(payload.sql)
    values = payload.model_dump(exclude={'revision'})
    return store(request).insert({**values, 'created_by': user.id}).execute().data[0]


@router.put('/queries/{query_id}')
def update_query(query_id: UUID, payload: SavedQuery, request: Request, user=Depends(require_admin)):
    from .query import validate_query
    validate_query(payload.sql)
    values = {**payload.model_dump(), 'revision': payload.revision + 1, 'updated_at': datetime.now(timezone.utc).isoformat()}
    rows = store(request).update(values).eq('id', str(query_id)).eq('revision', payload.revision).execute().data
    if not rows:
        raise HTTPException(409, 'Query changed. Reload before saving.')
    return rows[0]


@router.delete('/queries/{query_id}', status_code=204)
def delete_query(query_id: UUID, revision: int, request: Request, user=Depends(require_admin)):
    rows = store(request).delete().eq('id', str(query_id)).eq('revision', revision).execute().data
    if not rows:
        raise HTTPException(409, 'Query changed. Reload before deleting.')


@router.post('/query')
def run(payload: RunQuery, request: Request, user=Depends(require_admin)):
    return execute_query(payload.sql, payload.start_at, payload.end_at, payload.project, request.app.state.runtime_policy)


@router.post('/queries/{query_id}/run')
def run_saved(query_id: UUID, payload: Filters, request: Request, user=Depends(require_admin)):
    rows = store(request).select('*').eq('id', str(query_id)).execute().data
    if not rows:
        raise HTTPException(404, 'Query not found.')
    return execute_query(rows[0]['sql'], payload.start_at, payload.end_at, payload.project, request.app.state.runtime_policy)


class RoleChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['member', 'admin']
    expected_role: Literal['member', 'admin']


@router.get('/users')
def users(request: Request, search: str = '', offset: int = 0, user=Depends(require_admin)):
    if len(search) > 200 or not 0 <= offset <= 1000000:
        raise HTTPException(422, 'Invalid search or page.')
    rows = role_rpc(request.app.state.analytics_supabase, 'commons_list_users', {'p_search': search.strip(), 'p_offset': offset})
    return {'users': rows[:50], 'has_more': len(rows) > 50}


@router.put('/users/{user_id}/role')
def change_role(user_id: UUID, payload: RoleChange, request: Request, user=Depends(require_admin)):
    role = role_rpc(request.app.state.analytics_supabase, 'commons_set_role', {
        'p_actor_id': str(user.id), 'p_user_id': str(user_id),
        'p_role': payload.role, 'p_expected_role': payload.expected_role,
    })
    return {'user_id': str(user_id), 'role': role}


@router.get('/role-history')
def role_history(request: Request, user=Depends(require_admin)):
    try:
        return (request.app.state.analytics_supabase.table('commons_role_audit')
                .select('id,user_id,actor_id,old_role,new_role,source,created_at,user_label,actor_label')
                .order('id', desc=True).limit(50).execute().data)
    except Exception as exc:
        raise HTTPException(503, 'Role history is temporarily unavailable.') from exc
