// Anonymous players arrive from the API with an opaque per-visit alias in place
// of their user id (backend/dice/anonymity.py). They have no public profile.
export function isAnonymousId(userId) {
  return typeof userId === 'string' && userId.startsWith('anon-');
}

// A profile link for a player, or null for an anonymous one.
export function profilePath(userId) {
  return userId && !isAnonymousId(userId) ? `/dice/profile/${userId}` : null;
}
