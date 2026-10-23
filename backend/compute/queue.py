"""Transactional single-slot queue; safe across API processes sharing one local disk."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


class Conflict(ValueError):
    pass


def encode(value):
    encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':'))
    if len(encoded.encode()) > 256 * 1024:
        raise ValueError('Job metadata exceeds 256 KiB; use artifact references')
    return encoded


class Queue:
    def __init__(self, path, registry, clock=time.time):
        self.path, self.registry, self.clock = str(path), registry, clock
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        Path(path).touch(mode=0o600, exist_ok=True)
        with self.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, type TEXT NOT NULL,
                dedup TEXT, payload TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                claim TEXT, worker TEXT, lease REAL, deadline REAL,
                result TEXT, error TEXT, progress TEXT,
                UNIQUE(project, dedup))''')
            db.execute('CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created)')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def value(self, row, private=False):
        value = dict(row)
        for key in ('payload', 'result', 'progress'):
            value[key] = json.loads(value[key]) if value[key] is not None else None
        if not private:
            for key in ('claim', 'worker', 'lease', 'deadline', 'dedup'):
                value.pop(key)
        return value

    def submit(self, project, kind, payload, dedup=None):
        spec = self.registry.get(kind)
        if spec.project != project:
            raise PermissionError('Job belongs to a different project')
        payload = encode(spec.input.model_validate(payload).model_dump(mode='json'))
        with self.transaction() as db:
            if dedup is not None:
                previous = db.execute('SELECT * FROM jobs WHERE project=? AND dedup=?', (project, dedup)).fetchone()
                if previous:
                    if previous['type'] != kind or previous['payload'] != payload:
                        raise Conflict('Idempotency key already used for another payload')
                    return self.value(previous)
            identifier = uuid4().hex
            db.execute('INSERT INTO jobs(id,project,type,dedup,payload,state,created) VALUES(?,?,?,?,?,?,?)',
                       (identifier, project, kind, dedup, payload, 'queued', self.clock()))
            return self.value(db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone())

    def recover(self, db):
        for row in db.execute("SELECT * FROM jobs WHERE state='running' AND lease<=?", (self.clock(),)).fetchall():
            spec = self.registry.jobs.get(row['type'])
            retry = spec and row['attempts'] < spec.max_attempts
            db.execute('UPDATE jobs SET state=?, claim=NULL, error=? WHERE id=?',
                       ('queued' if retry else 'failed', 'Worker lease expired', row['id']))

    def status(self, project, identifier):
        with self.transaction() as db:
            self.recover(db)
            row = db.execute('SELECT * FROM jobs WHERE id=? AND project=?', (identifier, project)).fetchone()
            if row is None:
                raise KeyError(identifier)
            return self.value(row)

    def claim(self, worker, types, capacity):
        with self.transaction() as db:
            self.recover(db)
            # v1 deliberately allows one running job across all projects/workers.
            if db.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                return None
            for row in db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created, id").fetchall():
                spec = self.registry.jobs.get(row['type'])
                if row['type'] not in types or spec is None or not spec.resources.fits(capacity):
                    continue
                now = self.clock()
                db.execute("UPDATE jobs SET state='running', attempts=attempts+1, claim=?, worker=?, lease=?, deadline=?, progress=NULL WHERE id=?",
                           (uuid4().hex, worker, now + min(120, spec.timeout_seconds), now + spec.timeout_seconds, row['id']))
                value = self.value(db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone(), private=True)
                value['resources'] = spec.resources.model_dump()
                value['timeout_seconds'] = spec.timeout_seconds
                return value
        return None

    def owned(self, db, identifier, claim):
        row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
        if row is None or row['claim'] != claim:
            raise Conflict('Stale or unknown claim')
        if row['state'] == 'succeeded':
            return row
        if row['state'] != 'running' or row['lease'] <= self.clock():
            raise Conflict('Claim has expired')
        return row

    def heartbeat(self, identifier, claim, progress):
        progress = encode(progress)
        with self.transaction() as db:
            row = self.owned(db, identifier, claim)
            if row['state'] != 'running':
                raise Conflict('Job is already finished')
            db.execute('UPDATE jobs SET lease=?, progress=? WHERE id=?',
                       (min(self.clock() + 120, row['deadline']), progress, identifier))
        return {'ok': True}

    def finish(self, identifier, claim, result=None, error=None):
        with self.transaction() as db:
            row = self.owned(db, identifier, claim)
            spec = self.registry.get(row['type'])
            if row['state'] == 'succeeded':
                if error is not None or encode(spec.output.model_validate(result).model_dump(mode='json')) != row['result']:
                    raise Conflict('Job already completed with another result')
                return {'ok': True}
            if error is None:
                result = encode(spec.output.model_validate(result).model_dump(mode='json'))
                db.execute("UPDATE jobs SET state='succeeded', result=?, error=NULL WHERE id=?", (result, identifier))
            else:
                state = 'queued' if row['attempts'] < spec.max_attempts else 'failed'
                db.execute('UPDATE jobs SET state=?, error=?, claim=NULL WHERE id=?', (state, error[:1000], identifier))
        return {'ok': True}
