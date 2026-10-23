import React from 'react';

// Hand-inked travel doodles: 24px grid, round ink strokes, one soft fill via --fill and paper highlights.
// Decorative only: always pair with a visible text label.
const paper = 'var(--paper-light, #f2eadb)';
const butter = 'var(--butter, #f0c477)';

function Doodle({ size = 24, children, className }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false" className={className}
    fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
}

export const Bowl = (props) => <Doodle {...props}>
  <path d="M8.2 6.6c-.8-1 .7-1.8-.1-2.9M11.6 6.4c-.8-1 .7-1.8-.1-2.9" strokeWidth="1.4" />
  <path d="M14.2 9.4 20.4 3.6M15.6 9.6l5.6-4.2" strokeWidth="1.4" />
  <path d="M3.4 10.4h17.2c-.2 4.5-3.6 7.9-8.6 7.9s-8.4-3.4-8.6-7.9Z" fill="var(--fill, #e6b49a)" />
  <path d="M6.6 13.2c1.2 1.6 3 2.4 5.2 2.4" stroke={paper} strokeWidth="1.3" />
  <path d="M9.2 18.1 8.6 20.4h6.8l-.6-2.3" />
</Doodle>;

export const Cabin = (props) => <Doodle {...props}>
  <path d="M15.6 6.4V3.8h2.3v4.4" />
  <path d="M4.6 11.2v8.2c0 .5.4.9.9.9h13c.5 0 .9-.4.9-.9v-8.2" fill="var(--fill, #b9c0c1)" />
  <path d="M2.6 11.9 11.4 4.2c.4-.3.9-.3 1.2 0l8.8 7.7" />
  <path d="M10.2 20.3v-4.6c0-.5.4-.9.9-.9h1.8c.5 0 .9.4.9.9v4.6" fill={paper} />
  <rect x="6.6" y="12.2" width="2.8" height="2.6" rx=".6" fill={butter} />
  <rect x="14.6" y="12.2" width="2.8" height="2.6" rx=".6" fill={butter} />
</Doodle>;

export const Camper = (props) => <Doodle {...props}>
  <path d="M3.2 15.6V9.4c0-1.9 1.3-3.3 3.2-3.4l8.6-.2c1.6 0 2.9.8 3.6 2.2l1.9 3.7c.3.6.4 1.2.4 1.8v2.1c0 .7-.5 1.2-1.2 1.2H4.4c-.7 0-1.2-.5-1.2-1.2Z" fill="var(--fill, #c9cdb8)" />
  <path d="M6.3 8.6h4.2v3H5.6v-2.2c0-.5.3-.8.7-.8Z" fill={paper} />
  <path d="M13 8.5h3.4l1.5 3.1H13Z" fill={paper} />
  <path d="M3.4 13.4h17.2" strokeWidth="1.25" opacity=".55" />
  <circle cx="7.4" cy="17.2" r="1.9" fill={paper} />
  <circle cx="16.4" cy="17.2" r="1.9" fill={paper} />
</Doodle>;

export const Ticket = (props) => <Doodle {...props}>
  <path d="M3.4 7.2c0-.6.5-1.1 1.1-1.1h15c.6 0 1.1.5 1.1 1.1v2.3a2.5 2.5 0 0 0 0 5v2.3c0 .6-.5 1.1-1.1 1.1h-15c-.6 0-1.1-.5-1.1-1.1v-2.3a2.5 2.5 0 0 0 0-5Z" fill="var(--fill, #f3d79f)" />
  <path d="M15.4 6.4v11.2" strokeDasharray="1.2 2" strokeWidth="1.3" />
  <path d="m9.4 9.1.9 1.9 2 .3-1.5 1.4.4 2-1.8-1-1.8 1 .4-2-1.5-1.4 2-.3Z" fill={paper} strokeWidth="1.3" />
</Doodle>;

export const Bag = (props) => <Doodle {...props}>
  <path d="M5.2 8.4h13.6l-1 11c-.1.6-.5 1-1.1 1H7.3c-.6 0-1-.4-1.1-1Z" fill="var(--fill, #cfc0a3)" />
  <path d="M9 8.4V6.8a3 3 0 0 1 6 0v1.6" />
  <path d="M5.4 11.2h13.2" stroke={paper} strokeWidth="1.3" />
</Doodle>;

export const Suitcase = (props) => <Doodle {...props}>
  <path d="M9.2 6.6V4.9c0-.6.5-1 1-1h3.6c.5 0 1 .4 1 1v1.7" />
  <rect x="3.4" y="6.6" width="17.2" height="12.6" rx="2.6" fill="var(--fill, #e6b49a)" />
  <path d="M7.6 6.8v12.2M16.4 6.8v12.2" strokeWidth="1.3" opacity=".55" />
  <circle cx="11.2" cy="11.4" r="1.9" fill={butter} strokeWidth="1.3" />
  <rect x="11.6" y="14.2" width="3.4" height="2.4" rx=".6" fill={paper} strokeWidth="1.3" transform="rotate(-8 13.3 15.4)" />
  <path d="M6.4 19.2v1M17.6 19.2v1" />
</Doodle>;

export const Palm = (props) => <Doodle {...props}>
  <path d="M3.4 20.4c3-1.6 14.2-1.6 17.2 0" fill="var(--fill, #f3d79f)" />
  <path d="M12.4 19.6c.4-4 .2-7.4-1-10.6" />
  <path d="M11.4 9c-1.8-2.2-4.6-2.6-6.8-1.4 2.6.1 4.6.9 6.8 1.4Zm0 0c.8-2.6 3.4-4 6-3.4-2.2.9-4.2 2-6 3.4Zm0 0c2.4-.6 5 .4 6.2 2.6-2.2-.8-4.2-1.6-6.2-2.6Zm0 0c-2.2.4-4 2-4.4 4.2 1.4-1.6 2.8-3 4.4-4.2Z" fill="var(--fill, #b7c09f)" strokeWidth="1.4" />
  <circle cx="18.6" cy="4.4" r="1.4" fill={butter} strokeWidth="1.3" />
</Doodle>;

export const Mountain = (props) => <Doodle {...props}>
  <path d="M2.8 19.4 9.2 8.6c.4-.6 1.2-.6 1.6 0l2.6 4.3 1.6-2.4c.4-.6 1.2-.6 1.6 0l4 8.9Z" fill="var(--fill, #b9c0c1)" />
  <path d="m7.8 11 1.4 1 1.2-1 1.2 1.2" stroke={paper} strokeWidth="1.3" />
  <circle cx="17.6" cy="5" r="1.6" fill={butter} strokeWidth="1.3" />
</Doodle>;

export const Tent = (props) => <Doodle {...props}>
  <path d="M2.8 19.6 11.2 5.4c.4-.6 1.2-.6 1.6 0l8.4 14.2Z" fill="var(--fill, #e6b49a)" />
  <path d="m12 6.8-1 1.6M12 6.8l1 1.6" />
  <path d="M9.4 19.6 12 14l2.6 5.6" fill={paper} />
  <path d="M1.8 19.6h20.4" />
</Doodle>;

export const Snowflake = (props) => <Doodle {...props}>
  <circle cx="12" cy="12" r="8.6" fill="var(--fill, #c6d0d2)" stroke="none" />
  <path d="M12 5.2v13.6M6.1 8.6l11.8 6.8M6.1 15.4l11.8-6.8" />
  <path d="m10.2 6.2 1.8 1.4 1.8-1.4M10.2 17.8l1.8-1.4 1.8 1.4" strokeWidth="1.3" />
</Doodle>;

export const City = (props) => <Doodle {...props}>
  <path d="M3.4 20.2V11c0-.4.3-.7.7-.7h4.4V6.4c0-.4.3-.7.7-.7h5.2c.4 0 .7.3.7.7v6h4.6c.4 0 .7.3.7.7v7.1Z" fill="var(--fill, #cfc0a3)" />
  <path d="M10.8 8.8h.1M13.2 8.8h.1M10.8 11.6h.1M13.2 11.6h.1M5.8 13.4h.1M17.8 15.4h.1" strokeWidth="2.2" stroke={paper} />
  <path d="M2.4 20.2h19.2" />
</Doodle>;

export const Wave = (props) => <Doodle {...props}>
  <path d="M2.6 15.4c2-.1 3-2.6 4.7-2.6s2.7 2.6 4.7 2.6 3-2.6 4.7-2.6 2.7 2.5 4.7 2.6v4.8H2.6Z" fill="var(--fill, #b9c9c8)" />
  <path d="M2.6 19c2-.1 3-1.4 4.7-1.4S10 19 12 19s3-1.4 4.7-1.4 2.7 1.3 4.7 1.4" stroke={paper} strokeWidth="1.3" />
  <circle cx="15.6" cy="6.4" r="2.6" fill={butter} />
</Doodle>;

export const Plane = (props) => <Doodle {...props}>
  <path d="M3.2 13.6 19 6.4c1.1-.5 2.2.6 1.6 1.7l-1.3 2.3c-.3.5-.7.8-1.2 1L5.4 16.2c-.6.2-1.3-.1-1.5-.7Z" fill="var(--fill, #c6d0d2)" />
  <path d="m9.4 11.2-2.6-4.4c-.2-.4.1-.8.5-.8h1.2c.3 0 .5.1.7.3l4.4 3.4M10.6 14.6l1.6 4.2c.2.4.6.6 1 .5l1-.3c.4-.1.6-.6.4-1l-1.4-4.6" fill={paper} strokeWidth="1.4" />
</Doodle>;

// Per-trip stickers, chosen from the trip id so every trip keeps its own.
export const tripStickers = [
  { key: 'suitcase', icon: Suitcase, cover: '#b76845' },
  { key: 'palm', icon: Palm, cover: '#69755a' },
  { key: 'mountain', icon: Mountain, cover: '#6e7b7e' },
  { key: 'tent', icon: Tent, cover: '#c27c3d' },
  { key: 'snow', icon: Snowflake, cover: '#4f8580' },
  { key: 'city', icon: City, cover: '#7d6a9b' },
  { key: 'wave', icon: Wave, cover: '#3f7c8a' },
  { key: 'plane', icon: Plane, cover: '#a8606f' },
];
export function tripSticker(trip) {
  let hash = 11;
  for (const character of String(trip?.id || trip?.name || '')) hash = (Math.imul(hash, 33) + character.charCodeAt(0)) >>> 0;
  return tripStickers[hash % tripStickers.length];
}

export function TripStamp({ trip, size = 44 }) {
  const { icon: Icon, cover } = tripSticker(trip);
  return <span className="trips-stamp" style={{ '--cover': cover, width: size, height: size }} aria-hidden="true">
    <Icon size={Math.round(size * 0.6)} />
  </span>;
}
