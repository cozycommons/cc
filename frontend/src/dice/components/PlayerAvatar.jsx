import React from 'react';
import { Link } from 'react-router-dom';

const avatarIdentity = (profile) => {
  const seed = String(profile?.user_id || profile?.display_name || '?');
  let hash = [...seed].reduce((value, character) => ((value * 31) + character.charCodeAt(0)) >>> 0, 7);
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b);
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b);
  hash = (hash ^ (hash >>> 16)) >>> 0;
  return {
    hue: hash % 360,
    pips: (hash % 6) + 1,
    initial: profile?.display_name?.[0]?.toUpperCase() || '?',
  };
};

const pipPositions = {
  1: [[12, 12]],
  2: [[8, 8], [16, 16]],
  3: [[7, 7], [12, 12], [17, 17]],
  4: [[8, 8], [16, 8], [8, 16], [16, 16]],
  5: [[7, 7], [17, 7], [12, 12], [7, 17], [17, 17]],
  6: [[8, 6], [8, 12], [8, 18], [16, 6], [16, 12], [16, 18]],
};

export default function PlayerAvatar({ profile, size = 40, linkToProfile = true }) {
  const identity = avatarIdentity(profile);
  const content = profile?.avatar_url ? (
    <img
      src={profile.avatar_url}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        objectFit: 'cover',
        border: '1px solid var(--border-subtle)',
        display: 'block',
      }}
    />
  ) : (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        display: 'block',
        background: `linear-gradient(145deg, hsl(${identity.hue} 72% 55%), hsl(${(identity.hue + 42) % 360} 68% 34%))`,
        border: '1px solid color-mix(in srgb, var(--border-subtle) 70%, transparent)',
      }}
    >
      <rect x="4.5" y="4.5" width="15" height="15" rx="4" fill="rgba(255,255,255,.18)" stroke="rgba(255,255,255,.5)" />
      {pipPositions[identity.pips].map(([cx, cy]) => <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="1.45" fill="white" />)}
      <circle cx="18.2" cy="18.2" r="4" fill="rgba(8,8,16,.86)" stroke="rgba(255,255,255,.72)" strokeWidth=".65" />
      <text x="18.2" y="20" textAnchor="middle" fill="white" fontSize="5.1" fontWeight="800" fontFamily="system-ui, sans-serif">{identity.initial}</text>
    </svg>
  );

  if (!linkToProfile || !profile?.user_id) return content;
  return (
    <Link to={`/dice/profile/${profile.user_id}`} title={profile.display_name}>
      {content}
    </Link>
  );
}
