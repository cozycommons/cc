"""Commons account API under /account, authenticated by the Supabase session bearer."""
import secrets
import threading
import time
import urllib.error
from uuid import UUID

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from cc_mcp import connections
from commons_account import profile
from espn import accounts as espn_accounts, disney_login
from espn.espn_client import EspnAuthError, EspnError
from espn.routes import _default_season
from ig_logger.sinks.beli import accounts as beli_accounts
from ig_logger.sinks.beli.beli_client import BeliError, BeliUnauthorized
from partiful import accounts as partiful_accounts
from partiful.partiful_client import PartifulClient, PartifulCodeRejected, PartifulError, normalize_phone
from resy import accounts as resy_accounts
from resy.resy_client import ResyAuthError, ResyError
from trips.profiles import avatar_url

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
SIGN_IN = 'Sign in to manage your Cozy Commons account.'
NOT_FOUND = 'No such agent connection.'


def client(request):
    # Uncached: a disconnect must be visible to the very next list.
    return request.app.state.mcp_supabase


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, SIGN_IN)
    try:
        user = client(request).auth.get_user(credentials.credentials).user
    except AuthApiError:
        raise HTTPException(401, 'Your session expired. Please sign in again.')
    if not user:
        raise HTTPException(401, SIGN_IN)
    if getattr(user, 'is_anonymous', False):
        raise HTTPException(403, 'Sign in with Google to manage your account.')
    return user


class ProfileChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=profile.NAME_LIMIT)
    avatar_url: Optional[str] = None


def identity(user, row):
    """What every project header shows for the signed-in user."""
    return {'user_id': str(user.id), 'email': user.email,
            'display_name': row['display_name'], 'avatar_url': avatar_url(row['avatar_url'])}


@router.get('')
def get_account(request: Request, user=Depends(current_user)):
    """The caller's Commons identity, creating the profile row on first sign-in."""
    return identity(user, profile.own_profile(client(request), user))


@router.patch('/profile')
def patch_profile(changes: ProfileChanges, request: Request, user=Depends(current_user)):
    """Name and photo for every project. Venmo stays on /trips/me, which confirms ownership."""
    write = changes.model_dump(exclude_unset=True)
    if write.get('avatar_url') is not None and avatar_url(write['avatar_url']) is None:
        raise HTTPException(400, 'Use an http(s) image URL.')
    if not write:
        return identity(user, profile.own_profile(client(request), user))
    try:
        return identity(user, profile.update_profile(client(request), user.id, write, user=user))
    except ValueError as error:
        raise HTTPException(400, str(error))


def agent_oauth(request):
    """The connector's OAuth proxy, or 503 when agent access is not configured."""
    oauth = getattr(request.app.state, 'cc_mcp_oauth', None)
    if oauth is None:
        raise HTTPException(503, 'Agent connections are unavailable.')
    return oauth


@router.get('/connections')
def list_connections(request: Request, user=Depends(current_user)):
    """Active connections. `client_name` is self-reported by the agent; show `redirect_host` beside it."""
    agent_oauth(request)
    return connections.active_connections(client(request), user.id)


@router.delete('/connections/{connection_id}', status_code=204)
async def disconnect(connection_id: str, request: Request, user=Depends(current_user)):
    """Revoke one connection's access and refresh tokens. Repeating it deletes them again."""
    oauth = agent_oauth(request)
    try:
        connection_id = str(UUID(connection_id))
    except ValueError:
        raise HTTPException(404, NOT_FOUND)
    row = await run_in_threadpool(connections.own_connection, client(request), user.id, connection_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)  # Another user's connection looks exactly like a missing one.
    # Delete the tokens first, then mark: a failure never shows "disconnected" while tokens still work.
    # Delete even when already marked: the token store, not revoked_at, decides whether tokens work.
    await oauth._revoke_proxy_token_set(row['upstream_token_id'])
    if row['revoked_at'] is None:
        await run_in_threadpool(connections.mark_revoked, client(request), row['upstream_token_id'])
    return Response(status_code=204)


# Linked accounts: the user signs in to the third-party service here, on our own
# page, so neither the password nor a ccX_ token ever passes through an agent.
class PasswordLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # Printable ASCII only, so Unicode look-alikes cannot match another login.
    login: str = Field(min_length=1, max_length=200, pattern=r'^[\x20-\x7e]+$')
    # No max_length here: FastAPI's 422 body echoes the rejected input, so the route checks length.
    password: str = Field(min_length=1)


# 10 attempts per hour per worker, counted per Commons user for each service and per service
# login, so new Commons accounts cannot buy more password guesses against one third-party
# login, and connecting several services cannot lock a user out of the next one.
_CONNECT_ATTEMPTS: dict[str, list[float]] = {}
_CONNECT_LIMIT = 10
_CONNECT_WINDOW_S = 3600


def connect_rate_check(*keys):
    now = time.time()
    recent = {key: [t for t in _CONNECT_ATTEMPTS.get(key, []) if now - t < _CONNECT_WINDOW_S] for key in keys}
    if any(len(attempts) >= _CONNECT_LIMIT for attempts in recent.values()):
        raise HTTPException(429, 'Too many attempts. Try again in an hour.')
    for key, attempts in recent.items():
        _CONNECT_ATTEMPTS[key] = attempts + [now]


@router.get('/linked-accounts')
def linked_accounts(request: Request, user=Depends(current_user)):
    """Which third-party accounts the caller has connected; summaries hold no secrets."""
    return {'beli': beli_accounts.linked_account_summary(client(request), user.id),
            'resy': resy_accounts.linked_account_summary(client(request), user.id),
            'espn': espn_accounts.linked_account_summary(client(request), user.id),
            'partiful': partiful_accounts.linked_account_summary(client(request), user.id)}


@router.post('/linked-accounts/beli')
def connect_beli(body: PasswordLogin, request: Request, user=Depends(current_user)):
    """Connect (or refresh the password of) the caller's Beli account from its login."""
    if len(body.password) > 200:
        raise HTTPException(400, 'That password is longer than Beli allows.')
    connect_rate_check('beli-user:' + str(user.id), 'beli:' + beli_accounts.login_key(body.login))
    try:
        outcome, account = beli_accounts.connect_account_for_owner(
            client(request), str(user.id), body.login, body.password)
    except BeliUnauthorized:
        raise HTTPException(400, 'Beli did not accept that email or phone number and password.')
    except (BeliError, urllib.error.URLError, TimeoutError):  # urllib raises the last two when Beli is unreachable
        raise HTTPException(502, 'Beli did not answer. Try again in a minute.')
    except beli_accounts.AccountError:
        raise HTTPException(503, 'Could not save your Beli login. Try again later.')
    if outcome == 'other_owner':
        raise HTTPException(409, 'This Beli account is connected to another Cozy Commons user. '
                                 'Sign in as that user to manage it.')
    return {'status': outcome, 'account': {'id': account['id'], 'label': account['label']}}


@router.post('/linked-accounts/resy')
def connect_resy(body: PasswordLogin, request: Request, user=Depends(current_user)):
    """Connect (or refresh the password of) the caller's Resy account from its email."""
    if len(body.password) > 200:
        raise HTTPException(400, 'That password is longer than Resy allows.')
    if '@' not in body.login:
        raise HTTPException(400, 'Enter the email you use to sign in to Resy.')
    connect_rate_check('resy-user:' + str(user.id), 'resy:' + resy_accounts.login_key(body.login))
    try:
        outcome, account = resy_accounts.connect_account_for_owner(
            client(request), str(user.id), body.login, body.password)
    except ResyAuthError:
        raise HTTPException(400, 'Resy did not accept that email and password.')
    except (ResyError, urllib.error.URLError, TimeoutError):  # the client wraps URLError; a read timeout escapes it
        raise HTTPException(502, 'Resy did not answer. Try again in a minute.')
    except resy_accounts.AccountError:
        raise HTTPException(503, 'Could not save your Resy login. Try again later.')
    if outcome == 'other_owner':
        raise HTTPException(409, 'This Resy account is connected to another Cozy Commons user. '
                                 'Sign in as that user to manage it.')
    return {'status': outcome, 'account': account}


class EspnLogin(PasswordLogin):
    """The MyDisney login ESPN uses. Without league_id, the account's basketball leagues are looked up."""
    league_id: Optional[int] = Field(default=None, ge=1)
    season: Optional[int] = Field(default=None, ge=2019, le=2100)
    enable_automation: bool = True


class EspnCookies(BaseModel):
    model_config = ConfigDict(extra='forbid')

    league_id: int = Field(ge=1)
    season: int = Field(ge=2019, le=2100)
    # No constraints on the cookies: FastAPI's 422 body echoes the rejected input, so the route checks them.
    espn_s2: str
    swid: str
    enable_automation: bool = True


ESPN_REFUSED = ('ESPN did not accept those cookies for that league. Copy fresh espn_s2 and SWID cookies '
                'and check the league ID and season.')
ESPN_DOWN = 'ESPN did not answer. Try again in a minute.'


def espn_connect(request, user, *, swid_proven, **team):
    """Shared tail of both ESPN forms: probe, reuse or create, link."""
    try:
        outcome, account = espn_accounts.connect_account_for_owner(
            client(request), str(user.id), swid_proven=swid_proven, **team)
    except EspnAuthError:
        raise HTTPException(400, ESPN_REFUSED)
    except EspnError as error:
        if error.status == 404:
            raise HTTPException(400, 'ESPN has no basketball league with that ID for that season.')
        raise HTTPException(502, ESPN_DOWN)
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(502, ESPN_DOWN)
    except espn_accounts.AccountError:
        raise HTTPException(503, 'Could not save your ESPN login. Try again later.')
    if outcome == 'other_owner':
        raise HTTPException(409, 'This ESPN team is connected to another Cozy Commons user. '
                                 'Sign in as that user to manage it.')
    if outcome == 'unproven':
        raise HTTPException(409, 'This ESPN team is already set up on Cozy Commons. If it is yours, sign in with '
                                 'your ESPN email and password, or enter the cce_ token from your earlier setup.')
    # Legacy /espn reads accounts through the API's TTL cache (one per process; production runs
    # one worker). Drop it so a cce_ token retired just now stops working at once.
    cached = getattr(request.app.state, 'supabase', None)
    if hasattr(cached, 'clear_cache'):
        cached.clear_cache()
    return {'status': outcome, 'account': account}


@router.post('/linked-accounts/espn')
def connect_espn(body: EspnLogin, request: Request, user=Depends(current_user)):
    """Connect the caller's ESPN team by signing in to MyDisney once; the password is never stored."""
    if len(body.password) > 200:
        raise HTTPException(400, 'That password is longer than ESPN allows.')
    if '@' not in body.login:
        raise HTTPException(400, 'Enter the email you use to sign in to ESPN.')
    connect_rate_check('espn-user:' + str(user.id), 'espn:' + body.login.strip().lower())  # ASCII by the model
    season = body.season or _default_season()
    try:
        cookies = disney_login.login(body.login, body.password)
    except (disney_login.InvalidCredentialsError, disney_login.AccountNotFoundError):
        # One message for both, so the form does not reveal which emails have ESPN accounts.
        raise HTTPException(400, 'ESPN did not accept that email and password.')
    except disney_login.ChallengeRequiredError:
        raise HTTPException(400, 'ESPN asked for a verification step. Sign in at espn.com once, '
                                 'then try again, or connect with cookies or the cce_ token from your earlier setup.')
    except (disney_login.DisneyLoginError, urllib.error.URLError, TimeoutError):
        raise HTTPException(502, ESPN_DOWN)
    # Always look up the account's own leagues: a chosen league_id must be one of them, so a
    # MyDisney claim is only ever made for a team this login actually holds.
    try:
        leagues = disney_login.discover_basketball_leagues(cookies['espn_s2'], cookies['swid'], season)
    except (disney_login.DisneyLoginError, urllib.error.URLError, TimeoutError):
        raise HTTPException(502, ESPN_DOWN)
    league_id = body.league_id
    if league_id is not None:
        if league_id not in {entry['league_id'] for entry in leagues}:
            raise HTTPException(400, f'That league is not one of your ESPN basketball leagues for the {season} season.')
    else:
        if not leagues:
            raise HTTPException(400, f'No ESPN fantasy basketball league found for the {season} season.')
        if len(leagues) > 1:
            # Nothing is stored yet; the page asks which league and signs in again with it.
            return {'status': 'league_selection_required', 'season': season,
                    'leagues': [{'league_id': entry['league_id'], 'name': entry['name'],
                                 'team_name': entry['team_name']} for entry in leagues]}
        league_id = leagues[0]['league_id']
    return espn_connect(request, user, swid_proven=True, league_id=league_id, season=season,
                        espn_s2=cookies['espn_s2'], swid=cookies['swid'],
                        enable_automation=body.enable_automation)


@router.post('/linked-accounts/espn/cookies')
def connect_espn_cookies(body: EspnCookies, request: Request, user=Depends(current_user)):
    """Connect the caller's ESPN team from espn_s2 and SWID cookies copied from a signed-in browser."""
    espn_s2, swid = body.espn_s2.strip(), body.swid.strip()
    if not 1 <= len(espn_s2) <= 2000 or not espn_s2.isascii() or not espn_s2.isprintable():
        raise HTTPException(400, 'Paste the espn_s2 cookie value.')
    if not 1 <= len(swid) <= 64 or not swid.isascii() or not swid.isprintable():
        raise HTTPException(400, 'Paste the SWID cookie value, such as {XXXXXXXX-XXXX-...}.')
    connect_rate_check('espn-user:' + str(user.id), 'espn-swid:' + espn_accounts.swid_key(swid))
    return espn_connect(request, user, swid_proven=False, league_id=body.league_id, season=body.season,
                        espn_s2=espn_s2, swid=swid, enable_automation=body.enable_automation)


class PartifulPhone(BaseModel):
    model_config = ConfigDict(extra='forbid')

    phone: str = Field(min_length=1, max_length=32, pattern=r'^[\x20-\x7e]+$')


class PartifulCode(PartifulPhone):
    # No constraints here: FastAPI's 422 body echoes the rejected input, so the route checks the code.
    code: str


def partiful_phone(raw):
    try:
        return normalize_phone(raw)
    except PartifulError:
        raise HTTPException(400, 'Enter a 10-digit US number or a + international number.')


PARTIFUL_DOWN = 'Partiful did not answer. Try again in a minute.'
# A texted code may be verified only by the Commons user who asked for it, for that phone, within
# 10 minutes, and only until it signs in once. One pending challenge per user per worker (a new
# send replaces it), kept in memory like the attempt counters; production runs one worker.
# A verify reserves its challenge by id under the lock, calls Partiful without the lock, then
# consumes or restores only that challenge, so it can never consume one a later send replaced.
_PARTIFUL_CHALLENGES: dict[str, dict] = {}
_PARTIFUL_CHALLENGE_S = 600
_PARTIFUL_LOCK = threading.Lock()


def _prune_partiful_challenges(now):
    for user_id in [u for u, pending in _PARTIFUL_CHALLENGES.items() if pending['expires'] < now]:
        del _PARTIFUL_CHALLENGES[user_id]


def store_partiful_challenge(user_id, phone):
    with _PARTIFUL_LOCK:
        now = time.time()
        _prune_partiful_challenges(now)
        _PARTIFUL_CHALLENGES[user_id] = {'id': secrets.token_hex(8), 'phone': phone,
                                         'expires': now + _PARTIFUL_CHALLENGE_S, 'reserved': False}


def reserve_partiful_challenge(user_id, phone):
    """The id of the caller's unexpired, unreserved challenge for this phone, now reserved; else None."""
    with _PARTIFUL_LOCK:
        _prune_partiful_challenges(time.time())
        pending = _PARTIFUL_CHALLENGES.get(user_id)
        if pending is None or pending['phone'] != phone or pending['reserved']:
            return None
        pending['reserved'] = True
        return pending['id']


def settle_partiful_challenge(user_id, challenge_id, consumed):
    """Consume (after Partiful accepted the code) or release the reserved challenge, if it is still that one."""
    with _PARTIFUL_LOCK:
        pending = _PARTIFUL_CHALLENGES.get(user_id)
        if pending is None or pending['id'] != challenge_id:
            return
        if consumed:
            del _PARTIFUL_CHALLENGES[user_id]
        else:
            pending['reserved'] = False


@router.post('/linked-accounts/partiful/code')
def send_partiful_code(body: PartifulPhone, request: Request, user=Depends(current_user)):
    """Step 1: text a Partiful sign-in code to the phone. Counted per user and per phone, so it cannot spam one."""
    phone = partiful_phone(body.phone)
    connect_rate_check('partiful-user:' + str(user.id), 'partiful:' + phone)
    try:
        PartifulClient.send_auth_code(phone)
    except (PartifulError, urllib.error.URLError, TimeoutError):  # the client wraps URLError; a read timeout escapes it
        raise HTTPException(502, PARTIFUL_DOWN)
    store_partiful_challenge(str(user.id), phone)
    return {'status': 'code_sent', 'phone': phone}


@router.post('/linked-accounts/partiful')
def connect_partiful(body: PartifulCode, request: Request, user=Depends(current_user)):
    """Step 2: connect the Partiful account the texted code signs in to."""
    phone = partiful_phone(body.phone)
    code = body.code.strip()
    if not (4 <= len(code) <= 10 and code.isascii() and code.isdigit()):
        raise HTTPException(400, 'Enter the number Partiful texted you.')
    connect_rate_check('partiful-user:' + str(user.id), 'partiful:' + phone)
    challenge = reserve_partiful_challenge(str(user.id), phone)
    if challenge is None:
        raise HTTPException(400, 'Send a code to this number first, then enter it within 10 minutes.')
    consumed = False
    try:
        outcome, account = partiful_accounts.connect_account_for_owner(client(request), str(user.id), phone, code)
        consumed = True  # Partiful accepted the code: it signs in only once here
    except PartifulCodeRejected:
        raise HTTPException(400, 'Partiful did not accept that code. Check it or send a new one.')
    except PartifulError as error:
        if error.status is not None and 400 <= error.status < 500 and error.status != 429:
            raise HTTPException(400, 'Partiful did not accept that code. Check it or send a new one.')
        raise HTTPException(502, PARTIFUL_DOWN)
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(502, PARTIFUL_DOWN)
    except partiful_accounts.AccountError:
        raise HTTPException(503, 'Could not save your Partiful sign-in. Try again later.')
    finally:
        settle_partiful_challenge(str(user.id), challenge, consumed)
    if outcome == 'other_owner':
        raise HTTPException(409, 'This Partiful account is connected to another Cozy Commons user. '
                                 'Sign in as that user to manage it.')
    return {'status': outcome, 'account': account}


class EspnToken(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # No constraints here: FastAPI's 422 body echoes the rejected input, so the route checks the token.
    token: str


@router.post('/linked-accounts/espn/token')
def claim_espn_token(body: EspnToken, request: Request, user=Depends(current_user)):
    """Link a legacy ESPN account with its cce_ token. Only this page takes one; no agent tool does.

    The way back for a legacy user whose cookies expired and whose MyDisney login is challenged:
    claim the row here, then refresh its cookies with /espn/cookies. The claim is unproven.
    """
    token = body.token.strip()
    if not (token.startswith('cce_') and 20 <= len(token) <= 100 and token.isascii() and token.isprintable()):
        raise HTTPException(400, 'Paste the cce_ token from your earlier ESPN setup.')
    connect_rate_check('espn-user:' + str(user.id))
    try:
        outcome, account = espn_accounts.link_account_by_token(client(request), token, str(user.id))
    except espn_accounts.AccountError:
        raise HTTPException(400, 'No ESPN account matches that token.')
    if outcome == 'other_owner':
        raise HTTPException(409, 'This ESPN team is connected to another Cozy Commons user. '
                                 'Sign in as that user to manage it.')
    return {'status': outcome, 'account': account}
