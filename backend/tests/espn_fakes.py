"""Synthetic ESPN accounts and a fake ESPN Fantasy league for connector tests. No network.

League holds one account's league state in ESPN's payload shapes and applies
transactions the way ESPN would; FakeEspn serves it in-process, and the loopback
OAuth exercise serves the same state over HTTP.
"""
import copy
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import uuid4

from cryptography.fernet import Fernet

from espn import accounts
from espn.espn_client import EspnWriteUncertain

PG, SG, SF, PF, C, G, F, UTIL, BE, IR = 0, 1, 2, 3, 4, 5, 6, 11, 12, 13
ALL_SLOTS = [PG, SG, SF, PF, C, G, F, UTIL, BE]
PERIOD = 11
OWN_TEAM, RIVAL_TEAM, RIVAL_SWID = 7, 8, '{SYNTHETIC-RIVAL}'
FREE_AGENT, RIVAL_STAR, BENCHED, IDLE, DROP = 9001, 201, 101, 111, 105
FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01


def player(pid, pro_team, value):
    return {'id': pid, 'fullName': f'Synthetic Player {pid}', 'proTeamId': pro_team, 'defaultPositionId': SF,
            'eligibleSlots': list(ALL_SLOTS), 'injuryStatus': 'ACTIVE',
            'stats': [{'statSourceId': 1, 'statSplitTypeId': 5, 'scoringPeriodId': PERIOD,
                       'appliedTotal': float(value)}]}


def entry(pid, slot, info):
    return {'playerId': pid, 'lineupSlotId': slot, 'playerPoolEntry': {'player': info}}


class League:
    """One account's league. Pro teams 1 and 2 play in PERIOD; pro team 30 is idle.

    The lineup starts wrong: scheduled BENCHED sits on the bench while idle IDLE
    holds a UTIL slot. answer_lost: record the next write, then answer 504.
    hidden: also keep recorded writes out of reads until reveal().
    """

    def __init__(self, swid, label='synthetic', league_id=999, season=2027):
        self.swid, self.label, self.league_id, self.season = swid, label, league_id, season
        starters = [PG, SG, SF, PF, C, G, F, UTIL, UTIL]
        own = [entry(101 + i, slot, player(101 + i, 1 + i % 2, 30 - i)) for i, slot in enumerate(starters)]
        own[0]['lineupSlotId'] = BE
        own.append(entry(110, BE, player(110, 2, 18)))
        own.append(entry(IDLE, UTIL, player(IDLE, 30, 15)))
        own += [entry(pid, BE, player(pid, 30, 10)) for pid in (112, 113)]
        rival = [entry(RIVAL_STAR, BE, player(RIVAL_STAR, 1, 40)), entry(202, BE, player(202, 2, 12))]
        self.teams = {OWN_TEAM: own, RIVAL_TEAM: rival}
        self.pool = [{'id': FREE_AGENT, 'onTeamId': 0, 'player': player(FREE_AGENT, 1, 22)}]
        self.transactions, self.sends, self.queued = [], [], []
        self.answer_lost = self.hidden = False
        self.ids = 0

    def payload(self, views=()):
        teams = [{'id': team_id, 'name': 'Synthetic Squad' if team_id == OWN_TEAM else 'Synthetic Rivals',
                  'abbrev': 'SYN' if team_id == OWN_TEAM else 'RIV',
                  'owners': [self.swid if team_id == OWN_TEAM else RIVAL_SWID],
                  'record': {'overall': {'wins': 3, 'losses': 1, 'pointsFor': 400.0, 'pointsAgainst': 380.0}},
                  'roster': {'entries': copy.deepcopy(entries)}} for team_id, entries in self.teams.items()]
        return {
            'id': self.league_id, 'seasonId': self.season,
            'status': {'currentScoringPeriod': PERIOD, 'firstScoringPeriod': 1, 'currentMatchupPeriod': 2},
            'settings': {'name': 'Synthetic League', 'size': 2,
                         'rosterSettings': {'lineupSlotCounts': {'0': 1, '1': 1, '2': 1, '3': 1, '4': 1, '5': 1,
                                                                 '6': 1, '11': 3, '12': 3, '13': 1}},
                         'scoringSettings': {'scoringItems': [{'statId': 0, 'points': 1.0}]},
                         'tradeSettings': {'deadlineDate': FAR_FUTURE_MS}},
            'members': [{'id': self.swid, 'displayName': self.label},
                        {'id': RIVAL_SWID, 'displayName': 'Synthetic rival'}],
            'teams': teams,
            'proGamesByScoringPeriod': {str(PERIOD): [{'homeProTeamId': 1, 'awayProTeamId': 2}]},
            'transactions': copy.deepcopy(self.transactions),
            'schedule': [], 'draftDetail': {'picks': []},
        }

    def league_players(self):
        rostered = [{'id': e['playerId'], 'onTeamId': team_id, 'player': e['playerPoolEntry']['player']}
                    for team_id, entries in self.teams.items() for e in entries]
        return copy.deepcopy(self.pool + rostered)

    def move(self, pid, to_team):
        source = next((team for team, rows in self.teams.items() if any(e['playerId'] == pid for e in rows)), None)
        if source is None:
            row = next(p for p in self.pool if p['id'] == pid)
            self.pool.remove(row)
            moved = entry(pid, BE, row['player'])
        else:
            moved = next(e for e in self.teams[source] if e['playerId'] == pid)
            self.teams[source].remove(moved)
            moved['lineupSlotId'] = BE
        if to_team:
            self.teams[to_team].append(moved)
        else:
            self.pool.append({'id': pid, 'onTeamId': 0, 'player': moved['playerPoolEntry']['player']})

    def write(self, kind, apply, answer):
        """Record one write as ESPN would; then answer, or lose the answer."""
        self.sends.append(kind)
        if self.hidden:
            self.queued.append(apply)
        else:
            apply()
        if self.answer_lost:
            self.answer_lost = False
            raise EspnWriteUncertain(f'ESPN {kind} transaction -> 504', status=504)
        return answer

    def reveal(self):
        self.hidden = False
        for apply in self.queued:
            apply()
        self.queued.clear()

    def transaction(self, kind, status, team_id, items):
        self.ids += 1
        self.transactions.append({'id': f'synthetic-txn-{self.ids}', 'type': kind, 'status': status,
                                  'teamId': team_id, 'items': items})
        return self.transactions[-1]

    def lineup(self, team_id, items):
        def apply():
            rows = {e['playerId']: e for e in self.teams[team_id]}
            for item in items:
                rows[item['playerId']]['lineupSlotId'] = item['toLineupSlotId']
        return self.write('lineup', apply, {'status': 'EXECUTED'})

    def roster(self, team_id, moves):
        items = [{'playerId': m['playerId'], 'type': m['action'], 'fromTeamId': 0 if m['action'] == 'ADD' else team_id,
                  'toTeamId': team_id if m['action'] == 'ADD' else 0} for m in moves]

        def apply():
            for move in moves:
                self.move(move['playerId'], team_id if move['action'] == 'ADD' else 0)
            self.transaction('FREEAGENT', 'EXECUTED', team_id, items)
        return self.write('roster_edit', apply, {'id': f'synthetic-txn-{self.ids + 1}', 'status': 'EXECUTED',
                                                 'type': 'FREEAGENT'})

    def trade(self, team_id, counterparty, give, receive):
        items = ([{'playerId': pid, 'type': 'TRADE', 'fromTeamId': team_id, 'toTeamId': counterparty} for pid in give]
                 + [{'playerId': pid, 'type': 'TRADE', 'fromTeamId': counterparty, 'toTeamId': team_id}
                    for pid in receive])
        # An offer changes no roster until the counterparty accepts on ESPN.
        return self.write('trade', lambda: self.transaction('TRADE', 'PENDING', team_id, items),
                          {'id': f'synthetic-txn-{self.ids + 1}', 'status': 'PENDING', 'type': 'TRADE'})


class FakeEspn:
    """EspnClient's interface over the League of the login (SWID) it was built for."""

    def __init__(self, db, account):
        self.db, self.swid = db, account['swid']
        self.league_id, self.season = account['league_id'], account['season']
        db.espn_logins.append(self.swid)

    @property
    def league(self):
        if self.db.espn_failure:
            raise self.db.espn_failure
        return self.db.espn_leagues[self.swid]

    def get_league(self, views, scoring_period_id=None):
        return self.league.payload(views)

    def get_league_players(self, limit=1000):
        return self.league.league_players()

    def get_league_players_for_period(self, scoring_period_id, limit=1000):
        return self.league.league_players()

    def get_players(self, limit=300):
        return [row['player'] for row in self.league.league_players()]

    def post_lineup_transaction(self, member_id, team_id, scoring_period_id, items):
        assert member_id == self.swid
        return self.league.lineup(team_id, items)

    def post_roster_transaction(self, member_id, team_id, scoring_period_id, moves, on_waivers=False):
        assert member_id == self.swid
        return self.league.roster(team_id, moves)

    def post_trade_transaction(self, member_id, team_id, counterparty_team_id, scoring_period_id,
                               give_player_ids, receive_player_ids):
        assert member_id == self.swid
        return self.league.trade(team_id, counterparty_team_id, give_player_ids, receive_player_ids)


def install(db, monkeypatch):
    """Encrypt synthetic cookies with a throwaway key and route ESPN calls to FakeEspn."""
    monkeypatch.setenv('ESPN_CREDENTIALS_KEY', Fernet.generate_key().decode())
    db.espn_logins, db.espn_leagues, db.espn_failure = [], {}, None
    monkeypatch.setattr('espn.accounts.make_client_for_account', lambda account, **_: FakeEspn(db, account))


def add_account(db, owner=None, label='synthetic'):
    """Add an onboarded ESPN account with its own league; return (row, its plaintext cce_ token)."""
    token = 'cce_' + token_urlsafe(32)
    swid = '{' + str(uuid4()).upper() + '}'
    row = {'id': str(uuid4()), 'label': label, 'league_id': 999, 'season': 2027,
           'espn_s2_enc': accounts.encrypt_secret('synthetic-s2'), 'swid_enc': accounts.encrypt_secret(swid),
           'token_hash': accounts.hash_token(token), 'token_prefix': token[:12], 'lineup_automation_enabled': False,
           'owner_user_id': owner, 'swid': swid}
    db.espn_accounts.append(row)
    db.espn_leagues[swid] = League(swid, label)
    return row, token


def add_edit(db, account, status='pending', minutes=30):
    """Store a roster edit for an account, as propose_edit would."""
    expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    row = {'id': str(uuid4()), 'account_id': account['id'], 'league_id': account['league_id'],
           'season': account['season'], 'team_id': OWN_TEAM, 'add_player_id': FREE_AGENT, 'drop_player_id': DROP,
           'add_player': {'player_id': FREE_AGENT, 'on_waivers': False}, 'drop_player': {'player_id': DROP},
           'preview': f'Add Synthetic Player {FREE_AGENT} and drop Synthetic Player {DROP} — team {OWN_TEAM}',
           'status': status, 'error': None, 'espn_transaction': None, 'expires_at': expires, 'executed_at': None,
           'created_at': datetime.now(timezone.utc).isoformat()}
    db.espn_tables['espn_roster_edits'].append(row)
    return row


def sends(db):
    """Every write request, as (kind, SWID), across all synthetic leagues."""
    return [(kind, swid) for swid, league in db.espn_leagues.items() for kind in league.sends]

