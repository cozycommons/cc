from pathlib import Path
import json
import shutil

from fastapi import HTTPException

from .blobs import digest


class OriginalStore:
    def __init__(self, root, blobs=None):
        self.root = Path(root)
        self.blobs = blobs
        self.originals = self.root / 'originals'
        self.uploads = self.root / 'uploads'
        self.originals.mkdir(exist_ok=True, mode=0o700)
        self.uploads.mkdir(exist_ok=True, mode=0o700)

    def path(self, set_id, clip):
        current = self.originals / set_id / clip['file']
        return current if current.exists() else self.root / set_id / clip['file']

    def destination(self, set_id, clip):
        directory = self.originals / set_id
        directory.mkdir(exist_ok=True, mode=0o700)
        return directory / clip['file']

    def session_directory(self, set_id):
        directory = self.uploads / set_id
        directory.mkdir(exist_ok=True, mode=0o700)
        return directory

    def sessions(self):
        return [json.loads(path.read_text()) for path in self.uploads.glob('*/*.json') if not path.name.endswith('.transfer.json')]

    def publish(self, set_id, clip, partial):
        partial = Path(partial)
        source = partial if partial.exists() else self.path(set_id, clip)
        clip['sha256'] = digest(source)
        if clip.get('kind') == 'video':
            from .video import thumbnail
            thumbnail(source, self.root / set_id / f'{clip["id"]}.jpg')
        if self.blobs:
            clip['object_key'] = f'originals/{set_id}/{clip["id"]}/{clip["sha256"]}'
            self.record_blob(clip['object_key'], clip['bytes'])
            self.blobs.put(source, clip['object_key'])
        elif partial.exists():
            partial.replace(self.destination(set_id, clip))

    def materialize(self, set_id, clip, directory):
        if clip.get('object_key'):
            if not self.blobs:
                raise ValueError('This set requires its private media storage. Restore the storage configuration.')
            return self.blobs.materialize(clip['object_key'], directory / f'{clip["id"]}.original', clip['bytes'], clip['sha256'])
        return self.path(set_id, clip)

    def remove(self, set_id, clip):
        if clip.get('object_key'):
            if not self.blobs:
                raise ValueError('Restore media storage before removing this recording.')
            self.remove_blobs([clip['object_key']])
        self.path(set_id, clip).unlink(missing_ok=True)
        (self.root / set_id / f'{clip["id"]}.jpg').unlink(missing_ok=True)

    def record_blob(self, key, size):
        import hashlib
        from .worker import write_json
        folder = self.root / 'objects'
        folder.mkdir(exist_ok=True, mode=0o700)
        write_json(folder / (hashlib.sha256(key.encode()).hexdigest() + '.json'), {'key': key, 'bytes': size})

    def remove_blobs(self, keys):
        import hashlib
        self.blobs.remove(keys)
        for key in keys:
            (self.root / 'objects' / (hashlib.sha256(key.encode()).hexdigest() + '.json')).unlink(missing_ok=True)

    def usage(self):
        originals = work = 0
        objects = [json.loads(path.read_text()) for path in (self.root / 'objects').glob('*.json')] if self.blobs else []
        staged = set()
        if objects:
            for session in self.sessions():
                prefix = f'originals/{session["set_id"]}/{session["clip"]["id"]}/'
                if any(item['key'].startswith(prefix) for item in objects):
                    staged.add(self.uploads / session['set_id'] / f'{session["id"]}.part')
        for path in self.root.rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            if relative.parts[0] == 'originals' or path.name.endswith(('.upload', '.part')):
                if path not in staged:
                    originals += size
            else:
                work += size
        originals += sum(item['bytes'] for item in objects)
        return originals, work

    def admit(self, limits, incoming=0, work_needed=0, exclude=None, reclaim=None):
        originals, work = self.usage()
        reserved = sum(max(0, session['size'] - session['offset']) for session in self.sessions()
                       if session['state'] == 'uploading' and session['id'] != exclude)
        if work + work_needed > limits.work_bytes:
            raise HTTPException(507, 'Processing storage is full. Remove an old set or ask for more storage.')
        required = reserved + incoming + max(work_needed, limits.work_bytes - work, 0) + limits.free_bytes
        if shutil.disk_usage(self.root).free < required:
            raise HTTPException(507, 'The server is low on storage. Added recordings and the current mix are retained.')
        deficit = originals + reserved + incoming - limits.original_bytes
        if deficit > 0 and reclaim:
            reclaim(deficit)
            originals, _ = self.usage()
        if originals + reserved + incoming > limits.original_bytes:
            raise HTTPException(507, 'Recording storage is full. Remove old recordings or ask for more storage.')
