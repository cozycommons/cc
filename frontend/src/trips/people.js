// Stable per-person colours from the Wabi palette plus two muted companions.
const palette = ['#b76845', '#69755a', '#6e7b7e', '#d39155', '#694b36', '#a8606f', '#4f8580', '#7d6a9b'];

export function personColor(member) {
  const seed = String(member?.user_id || member?.id || member?.display_name || '?');
  let hash = 7;
  for (const character of seed) hash = (Math.imul(hash, 31) + character.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}

export const memberName = (member) => member?.display_name || member?.name || 'Unknown person';
export const firstName = (member) => memberName(member).split(/\s+/)[0];
export const findMember = (group, id) => group.members.find((member) => member.id === id);
export const myMember = (group, userId) => group.members.find((member) => member.user_id === userId);
