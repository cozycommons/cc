export function eventDate(set) {
  if (!set.starts_at) return '';
  try {
    const options = { timeZone: set.timezone || 'UTC', month: 'short', day: 'numeric', year: 'numeric' };
    return new Intl.DateTimeFormat(undefined, options).format(new Date(set.starts_at));
  } catch { return ''; }
}

export function eventRange(set) {
  if (!set.starts_at || !set.ends_at) return '';
  try {
    const format = new Intl.DateTimeFormat(undefined, {
      timeZone: set.timezone || 'UTC', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
    });
    return `${format.formatRange(new Date(set.starts_at), new Date(set.ends_at))} · ${(set.timezone || 'UTC').replaceAll('_', ' ')}`;
  } catch { return ''; }
}

export function matchesSearch(set, query) {
  const text = [set.name, set.artist, set.venue, set.starts_at, eventDate(set)].filter(Boolean).join(' ').toLocaleLowerCase();
  return query.trim().toLocaleLowerCase().split(/\s+/).every((word) => text.includes(word));
}

export function possibleDuplicates(sets, draft) {
  const normalize = (value) => (value || '').trim().toLocaleLowerCase().replace(/\s+/g, ' ');
  if (!draft.artist) return sets.filter((set) => normalize(set.name) === normalize(draft.name));
  return sets.filter((set) => {
    if (normalize(set.artist) !== normalize(draft.artist) || normalize(set.venue) !== normalize(draft.venue) || !set.starts_at) return false;
    try {
      const parts = new Intl.DateTimeFormat('en-CA', { timeZone: draft.timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(set.starts_at));
      const date = ['year', 'month', 'day'].map((type) => parts.find((part) => part.type === type).value).join('-');
      return date === draft.starts_at.slice(0, 10);
    } catch { return false; }
  });
}
