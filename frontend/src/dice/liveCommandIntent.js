const STORAGE_PREFIX = 'dice.live-command.v1';
const CANONICAL_PREFIX = 'dice.live-canonical.v1';

const storageKey = (userId, matchId) => (
  `${STORAGE_PREFIX}:${encodeURIComponent(userId)}:${encodeURIComponent(matchId)}`
);

const canonicalKey = (userId, matchId) => (
  `${CANONICAL_PREFIX}:${encodeURIComponent(userId)}:${encodeURIComponent(matchId)}`
);

const canonicalMarkerKey = (userId, matchId, version) => (
  `${canonicalKey(userId, matchId)}:${version}`
);

const validCommand = (command) => command
  && typeof command === 'object'
  && typeof command.client_command_id === 'string'
  && command.client_command_id.length > 0
  && Number.isInteger(command.expected_version)
  && command.expected_version >= 0
  && typeof command.kind === 'string'
  && command.kind.length > 0;

export const readLiveCommandIntent = (storage, userId, matchId) => {
  if (!storage || !userId || !matchId) return null;
  const key = storageKey(userId, matchId);
  try {
    const value = JSON.parse(storage.getItem(key));
    if (value?.version !== 1 || !['pending', 'review'].includes(value.state) || !validCommand(value.command)) {
      storage.removeItem(key);
      return null;
    }
    return value;
  } catch {
    try { storage.removeItem(key); } catch { /* Storage may be unavailable. */ }
    return null;
  }
};

export const writeLiveCommandIntent = (storage, userId, matchId, intent) => {
  if (!storage || !userId || !matchId || !validCommand(intent?.command)) return false;
  try {
    storage.setItem(storageKey(userId, matchId), JSON.stringify({
      version: 1,
      state: intent.state === 'review' ? 'review' : 'pending',
      command: intent.command,
    }));
    return true;
  } catch {
    return false;
  }
};

export const clearLiveCommandIntent = (storage, userId, matchId) => {
  if (!storage || !userId || !matchId) return;
  try { storage.removeItem(storageKey(userId, matchId)); } catch { /* Storage may be unavailable. */ }
};

export const readLiveCanonicalVersion = (storage, userId, matchId) => {
  if (!storage || !userId || !matchId) return 0;
  try {
    const base = canonicalKey(userId, matchId);
    let latest = Number(storage.getItem(base));
    if (!Number.isInteger(latest) || latest <= 0) latest = 0;
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (!key?.startsWith(`${base}:`)) continue;
      const version = Number(key.slice(base.length + 1));
      if (Number.isInteger(version) && version > latest) latest = version;
    }
    return latest;
  } catch { return 0; }
};

export const writeLiveCanonicalVersion = (storage, userId, matchId, version) => {
  if (!storage || !userId || !matchId || !Number.isInteger(version) || version <= 0) return false;
  try {
    storage.setItem(canonicalMarkerKey(userId, matchId, version), '1');
    return true;
  } catch { return false; }
};

export const clearLiveCanonicalVersion = (storage, userId, matchId, throughVersion = Infinity) => {
  if (!storage || !userId || !matchId) return;
  try {
    const base = canonicalKey(userId, matchId);
    const legacy = Number(storage.getItem(base));
    if (!Number.isInteger(legacy) || legacy <= throughVersion) storage.removeItem(base);
    const keys = [];
    for (let index = 0; index < storage.length; index += 1) keys.push(storage.key(index));
    keys.filter((key) => key?.startsWith(`${base}:`)).forEach((key) => {
      const version = Number(key.slice(base.length + 1));
      if (Number.isInteger(version) && version <= throughVersion) storage.removeItem(key);
    });
  } catch { /* Storage may be unavailable. */ }
};
