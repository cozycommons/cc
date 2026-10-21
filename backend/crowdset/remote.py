"""Persistent remote jobs and bounded direct transfers; no media bytes on the API."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import time
import httpx
from uuid import uuid4

from fastapi import HTTPException

from .blobs import BlobError
from .worker import write_json
from .youtube import canonical_url

HEX = re.compile(r'^[a-f0-9]{64}$')
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,179}$')
ANALYSIS = ('duration', 'expected_duration', 'quality', 'measurement', 'video', 'capture', 'alignment')


class RemoteJobs:
    def __init__(self, store):
        self.store = store
        self.root = store.root / 'remote-jobs'
        self.root.mkdir(exist_ok=True, mode=0o700)

    @staticmethod
    def generation(data):
        value = {'soundtrack': data.get('soundtrack_clip_id'), 'clips': [
            {k: c.get(k) for k in ('id', 'sha256', 'object_key', 'included', 'role')} for c in data['clips']]}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def jobs(self):
        return [json.loads(p.read_text()) for p in sorted(self.root.glob('*.json'))]

    def save(self, job):
        write_json(self.root / (job['id'] + '.json'), job)
        return job

    def admit(self, incoming=0):
        if sum(self.store.blobs.ledger().values()) + incoming > self.store.limits.original_bytes:
            raise HTTPException(507, 'Cloud storage is full. Remove old recordings or increase the storage budget.')

    def enqueue(self, data, kind='process', **details):
        existing = next((j for j in self.jobs() if j['set_id'] == data['id'] and j['kind'] == kind
                         and j['state'] in ('queued', 'running') and j.get('session_id') == details.get('session_id')), None)
        if existing:
            if kind == 'process' and existing['state'] == 'queued':
                data.update(status='queued', stage='Waiting for the PC worker…')
            self.store.save(data)
            return existing
        job = {'id': uuid4().hex, 'set_id': data['id'], 'kind': kind, 'state': 'queued',
               'created_at': time.time(), 'artifacts': {}, **details}
        self.save(job)
        if kind in ('process', 'youtube'):
            data.update(status='queued' if kind == 'process' else 'importing', stage='Waiting for the PC worker…')
            self.store.save(data)
        return job

    def claim(self):
        now = time.time()
        jobs = self.jobs()
        if any(j['state'] == 'running' and j.get('lease_until', 0) > now for j in jobs):
            return None
        for job in sorted(jobs, key=lambda j: (j['kind'] == 'process', j['created_at'])):
            if job['state'] not in ('queued', 'running'):
                continue
            try:
                data = self.store.get(job['set_id'])
            except HTTPException:
                continue
            if job['kind'] == 'process' and (job['set_id'] in self.store.batches or any(
                    j['set_id'] == job['set_id'] and j['kind'] != 'process' and j['state'] in ('queued', 'running') for j in jobs)):
                continue
            job.update(state='running', claim=uuid4().hex, lease_until=now + 120, started_at=now,
                       snapshot=deepcopy(data), base_revision=data.get('mix_revision'), generation=self.generation(data))
            # Each claim writes a fresh immutable output namespace; old attempts remain reserved.
            job.setdefault('abandoned_artifacts', []).extend(job.get('artifacts', {}).values())
            job['artifacts'] = {}
            self.save(job)
            data.update(status=('uploading' if job['kind'] == 'ingest' and job['set_id'] in self.store.batches else
                                'importing' if job['kind'] == 'youtube' else 'processing'),
                        stage='Starting on the PC worker…', processing_started_at=now)
            self.store.save(data)
            return {**deepcopy(job), 'limits': asdict(self.store.limits)}
        return None

    def owned(self, identity, claim, *, allow_complete=False):
        if not re.fullmatch('[a-f0-9]{32}', identity or ''):
            raise HTTPException(404, 'Job not found.')
        path = self.root / f'{identity}.json'
        job = json.loads(path.read_text()) if path.exists() else {}
        if allow_complete and job.get('state') == 'complete' and job.get('claim') == claim:
            return job
        if job.get('state') != 'running' or job.get('claim') != claim or job.get('lease_until', 0) <= time.time():
            raise HTTPException(409, 'Worker lease expired. The result has not been published.')
        current = self.store.get(job['set_id'])
        if job['kind'] == 'process' and self.generation(current) != job['generation']:
            raise HTTPException(409, 'Recordings changed during processing. A fresh claim is required.')
        if current.get('mix_revision') != job['base_revision']:
            raise HTTPException(409, 'The published cut changed. Claim a new job.')
        return job

    def heartbeat(self, job, stage):
        if time.time() - job['started_at'] > self.store.limits.job_seconds:
            raise HTTPException(409, 'Worker job exceeded its deadline.')
        job['lease_until'] = time.time() + 120
        self.save(job)
        data = self.store.get(job['set_id'])
        data['stage'] = str(stage)[:180]
        if job['kind'] == 'youtube':
            data['youtube_import']['stage'] = data['stage']
        data['processing'] = {'phase': 'remote', 'started_at': job['started_at'], 'updated_at': time.time()}
        self.store.save(data)
        return {'lease_until': job['lease_until']}

    def browser_prepare(self, session):
        if session['state'] != 'uploading':
            return {**self.store.public_session(session), 'direct': True}
        if not session.get('direct'):
            key = f"originals/{session['set_id']}/{session['clip']['id']}/{session['id']}"
            self.admit(session['size'])
            self.store.originals.record_blob(key, session['size'])
            session.update(direct=True, object_key=key)
            self.store.save_session(session)
        state = self.store.blobs.begin_direct(session['object_key'], session['size'], session['fingerprint'], 'application/octet-stream')
        if state and state.get('complete'):
            session['offset'] = session['size']
            self.store.save_session(session)
        self.touch_batch(session)
        return {**self.store.public_session(session), 'direct': True}

    def touch_batch(self, session):
        batch = self.store.batches.get(session['set_id'])
        if batch and batch['id'] == session.get('batch_id'):
            batch.update(deadline=time.monotonic() + 600, expires_at=time.time() + 600)
            data = self.store.get(session['set_id'])
            data['batch'] = {k: v for k, v in batch.items() if k != 'deadline'}
            self.store.save(data)

    def recover(self):
        for session in self.store.originals.sessions():
            if session.get('direct') and session['state'] == 'validating' and (self.store.directory(session['set_id']) / 'set.json').is_file():
                data = self.store.get(session['set_id'])
                self.enqueue(data, 'ingest', session_id=session['id'], owner=session['owner'],
                             input={'key': session['object_key'], 'bytes': session['size'], 'clip': session['clip']})

    def browser_ack(self, session, number):
        size = min(self.store.limits.chunk_bytes, session['size'] - (number - 1) * self.store.limits.chunk_bytes)
        if size <= 0 or (number - 1) * self.store.limits.chunk_bytes > session['offset']:
            raise HTTPException(409, 'Upload part is out of order.')
        session['offset'] = max(session['offset'], (number - 1) * self.store.limits.chunk_bytes + size)
        self.store.save_session(session)
        self.touch_batch(session)
        return {**self.store.public_session(session), 'direct': True}

    def browser_finish(self, session):
        if session['state'] == 'complete':
            return self.store.get(session['set_id'])
        self.store.blobs.finish_direct(session['object_key'], session['size'], session['fingerprint'])
        session.update(state='validating', expires_at=time.time() + self.store.limits.upload_seconds + self.store.limits.job_seconds)
        self.store.save_session(session)
        data = self.store.get(session['set_id'])
        self.enqueue(data, 'ingest', session_id=session['id'], owner=session['owner'],
                     input={'key': session['object_key'], 'bytes': session['size'], 'clip': session['clip']})
        data.update(stage='Waiting for the PC to check the recording…')
        return self.store.save(data)

    def collect(self, set_id):
        data = self.store.get(set_id)
        retained = {clip.get(k) for clip in data['clips'] + data.get('deleted_clips', [])
                    for k in ('object_key', 'thumbnail_object')}
        for revision in (data, data.get('previous_revision', {})):
            retained.update(revision.get(k) for k in ('mix_object', 'video_object'))
            retained.update((revision.get('preview_objects') or {}).values())
            retained.update(a.get('object') for a in (revision.get('composition') or {}).get('assets', {}).values())
        for job in self.jobs():
            if job['set_id'] != set_id:
                continue
            obsolete = list(job.get('abandoned_artifacts', []))
            if job['kind'] == 'process' and job['state'] in ('complete', 'failed'):
                obsolete.extend(job['artifacts'].values())
            keys = [a['key'] for a in obsolete if a['key'].startswith('mixes/') and a['key'] not in retained]
            if keys:
                try:
                    self.store.originals.remove_blobs(keys)
                except (OSError, ValueError, httpx.HTTPError):
                    pass  # Failed cleanup keeps its reservation and retries on the next publication.

    def reserve(self, job, name, size, checksum, mime):
        if not NAME.fullmatch(name) or '..' in name or not HEX.fullmatch(checksum):
            raise HTTPException(422, 'Invalid artifact identity.')
        maximum = self.store.limits.file_bytes if job['kind'] == 'youtube' else 4 * self.store.limits.file_bytes
        if type(size) is not int or not 0 < size <= maximum or len(job['artifacts']) >= 1000:
            raise HTTPException(413, 'Artifact exceeds the worker output bounds.')
        artifact = job['artifacts'].get(name)
        if artifact and (artifact['bytes'], artifact['sha256']) != (size, checksum):
            raise HTTPException(409, 'This artifact is immutable. Retry with a fresh claim.')
        if not artifact:
            self.admit(size)
            prefix = 'originals' if name == 'source.mp4' and job['kind'] == 'youtube' else 'mixes'
            key = f"{prefix}/{job['set_id']}/remote-{job['id']}-{job['claim']}/{name}"
            self.store.originals.record_blob(key, size)
            artifact = {'key': key, 'bytes': size, 'sha256': checksum, 'complete': False}
            job['artifacts'][name] = artifact
            self.save(job)
        if artifact['complete']:
            return artifact
        state = self.store.blobs.begin_direct(artifact['key'], size, checksum, mime)
        if state and state.get('complete'):
            artifact['complete'] = True
            self.save(job)
        return artifact

    def read(self, job, key):
        allowed = {c.get('object_key') for c in job['snapshot']['clips']}
        if job.get('input'):
            allowed.add(job['input']['key'])
        if key not in allowed or not key:
            raise HTTPException(403, 'This input is outside the claimed job.')
        return {'url': self.store.blobs.signed('GET', key)}

    def complete(self, job, name):
        artifact = job['artifacts'][name]
        self.store.blobs.finish_direct(artifact['key'], artifact['bytes'], artifact['sha256'])
        artifact['complete'] = True
        self.save(job)
        return artifact

    def publish(self, job, result):
        # JSON validation also rejects infinities and NaNs before touching live metadata.
        if len(json.dumps(result, allow_nan=False)) > 1024 ** 2:
            raise HTTPException(413, 'Worker result metadata is too large.')
        data = self.store.get(job['set_id'])
        if job['state'] == 'complete':
            return data
        def artifact(name):
            value = job['artifacts'].get(name)
            if not value or not value['complete']:
                raise HTTPException(409, 'Required output has not completed its transfer.')
            return value
        if job['kind'] in ('youtube', 'ingest'):
            if job['kind'] == 'youtube':
                original = artifact('source.mp4')
                clip = {'id': uuid4().hex, 'name': str(result['name'])[:180], 'bytes': original['bytes'],
                        'object_key': original['key'], 'source_url': job['url'], 'uploader': job['owner'],
                        'role': 'recording', 'included': True, 'kind': 'video'}
                if not clip['name'].lower().endswith('.mp4'):
                    raise HTTPException(422, 'YouTube output must be MP4.')
            else:
                clip = deepcopy(job['input']['clip'])
                clip['object_key'] = job['input']['key']
            checksum, duration = result.get('sha256'), result.get('duration')
            if not HEX.fullmatch(checksum or '') or type(duration) not in (int, float) or not 0 < duration <= self.store.limits.recording_seconds:
                raise HTTPException(422, 'Invalid recording analysis.')
            if job['kind'] == 'youtube' and checksum != original['sha256']:
                raise HTTPException(422, 'Original hash changed.')
            duplicate = next((c for c in data['clips'] if c.get('sha256') == checksum), None)
            if not duplicate and (len(data['clips']) >= self.store.limits.recordings or sum(c.get('expected_duration', c.get('duration', 0)) for c in data['clips']) + duration > self.store.limits.set_seconds):
                raise HTTPException(413, 'The set exceeds its recording or duration limit.')
            clip.update(sha256=checksum, expected_duration=duration, file=clip['id'] + '.upload')
            if result.get('thumbnail'):
                clip['thumbnail_object'] = artifact(result['thumbnail'])['key']
            if not duplicate:
                data['clips'].append(clip)
            if job['kind'] == 'ingest':
                session = self.store.session(data['id'], job['session_id'], job['owner'])
                session.update(state='complete', clip=duplicate or clip)
                self.store.save_session(session)
            else:
                data['youtube_import'].update(state='complete', stage='Downloaded on the PC', error=None)
            data.update(status=('ready' if data.get('playable') else 'idle'), dirty=data.get('dirty', False) or not bool(duplicate), error=None)
            self.store.save(data)
            job['state'] = 'complete'
            self.save(job)
            if duplicate:
                protected = {c.get(k) for c in data['clips'] + data.get('deleted_clips', []) for k in ('object_key', 'thumbnail_object')}
                redundant = ({clip['object_key']} | {a['key'] for a in job['artifacts'].values()}) - protected
                try:
                    self.store.originals.remove_blobs(list(set(redundant)))
                except (OSError, ValueError, httpx.HTTPError):
                    pass
                data['duplicate_clip_id'] = duplicate['id']
                if data.get('dirty') or data['id'] in self.store.batches:
                    self.store.queue(data)
            else:
                self.store.queue(data)
            return data
        allowed = ('timeline', 'video_timeline', 'scrub_previews')
        if not result.get('playable') or result.get('composition'):
            raise HTTPException(422, 'The remote cut must be a single playable file.')
        clips = result.get('clips', [])
        if [c.get('id') for c in clips] != [c['id'] for c in job['snapshot']['clips']]:
            raise HTTPException(422, 'Worker recording identities changed.')
        restored = []
        for original, analyzed in zip(job['snapshot']['clips'], clips):
            restored.append({**original, **{key: analyzed[key] for key in ANALYSIS if key in analyzed}})
        video = artifact('pending.mp4') if result.get('video_playable') else None
        audio = artifact('pending.wav')
        previews = deepcopy(result.get('scrub_previews') or {})
        preview_objects = {}
        for preview in previews.values():
            for name in preview['sheets']:
                preview_objects[name] = artifact(name)['key']
        visual = result.get('video_timeline') or {}
        if any(s.get('asset_id') for s in visual.get('segments', [])):
            raise HTTPException(422, 'Remote cut still contains client video inserts.')
        previous = {k: data.get(k) for k in ('mix_revision', 'mix_file', 'mix_object', 'mix_bytes', 'video_file',
                    'video_object', 'video_bytes', 'playable', 'video_playable', 'composition', 'scrub_previews', 'preview_objects')}
        data.update({key: result.get(key) for key in allowed}, clips=restored, previous_revision=previous,
                    previous_mix_object=data.get('mix_object'), previous_mix_bytes=data.get('mix_bytes', 0),
                    mix_revision=job['id'], mix_file='pending.wav', mix_object=audio['key'], mix_bytes=audio['bytes'],
                    video_file='pending.mp4' if video else None, video_object=video['key'] if video else None,
                    video_bytes=video['bytes'] if video else 0, composition=None, preview_objects=preview_objects,
                    playable=True, video_playable=bool(video), status='ready', error=None, dirty=False)
        data.pop('stage', None)
        data.pop('processing', None)
        self.store.save(data)
        job['state'] = 'complete'
        self.save(job)
        self.collect(data['id'])
        return data

    def fail(self, job, message):
        job.update(state='failed', error=str(message)[:500])
        self.save(job)
        data = self.store.get(job['set_id'])
        data.update(status='failed', error=job['error'], dirty=True)
        self.store.save(data)
        return {'state': 'failed'}
