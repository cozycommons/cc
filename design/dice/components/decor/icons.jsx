import React from 'react';

/* Small hand-drawn stroke icon set — Lucide-style (per the design system's
   iconography recommendation), used only as scenery placeholders inside
   ds-window art frames. Not a full icon system. */

function Base({ size = 48, strokeWidth = 1.5, children, style }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
    >
      {children}
    </svg>
  );
}

export function HouseIcon(props) {
  return (
    <Base {...props}>
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5.5 10v10h13V10" />
      <rect x="10" y="14" width="4" height="6" />
      <path d="M15.5 6.2V4h2v3.9" />
    </Base>
  );
}

export function TreesIcon(props) {
  return (
    <Base {...props}>
      <circle cx="8.5" cy="9.5" r="4.5" />
      <circle cx="15" cy="8" r="5.5" />
      <line x1="8.5" y1="14" x2="8.5" y2="20" />
      <line x1="15" y1="13.5" x2="15" y2="20" />
    </Base>
  );
}

export function RoadIcon(props) {
  return (
    <Base {...props}>
      <path d="M9 3 4 21" />
      <path d="M15 3l5 18" />
      <line x1="11.3" y1="8" x2="10.6" y2="10.5" />
      <line x1="10.2" y1="12.5" x2="9.5" y2="15" />
      <line x1="9.1" y1="17" x2="8.4" y2="19.5" />
    </Base>
  );
}

export function HillsIcon(props) {
  return (
    <Base {...props}>
      <path d="M2 19 8 9l4 6 3-4 7 8" />
      <path d="M2 19h20" />
    </Base>
  );
}

export function SunIcon(props) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="4.5" />
      <line x1="12" y1="2" x2="12" y2="4.5" />
      <line x1="12" y1="19.5" x2="12" y2="22" />
      <line x1="2" y1="12" x2="4.5" y2="12" />
      <line x1="19.5" y1="12" x2="22" y2="12" />
      <line x1="4.9" y1="4.9" x2="6.6" y2="6.6" />
      <line x1="17.4" y1="17.4" x2="19.1" y2="19.1" />
      <line x1="4.9" y1="19.1" x2="6.6" y2="17.4" />
      <line x1="17.4" y1="6.6" x2="19.1" y2="4.9" />
    </Base>
  );
}

export function MoonIcon(props) {
  return (
    <Base {...props}>
      <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z" />
    </Base>
  );
}

export function PawIcon(props) {
  return (
    <Base {...props} strokeWidth={0} fill="currentColor">
      <ellipse cx="12" cy="16" rx="4.6" ry="3.6" />
      <circle cx="6.2" cy="10.5" r="2" />
      <circle cx="10.3" cy="7.3" r="2" />
      <circle cx="14.7" cy="7.3" r="2" />
      <circle cx="18.2" cy="10.5" r="2" />
    </Base>
  );
}

export function PersonIcon(props) {
  return (
    <Base {...props}>
      <circle cx="12" cy="7" r="3.2" />
      <path d="M5.5 21v-2.2a6.5 6.5 0 0 1 13 0V21" />
    </Base>
  );
}

export function DogIcon(props) {
  return (
    <Base {...props}>
      <ellipse cx="13" cy="14.5" rx="6.5" ry="4" />
      <circle cx="6" cy="11" r="3" />
      <path d="M4.3 9.2 2.6 6.6" />
      <path d="M17 11.5c1.6-.4 3-.1 4 1" />
      <line x1="8" y1="18" x2="7.3" y2="21" />
      <line x1="11.5" y1="18.4" x2="11" y2="21" />
      <line x1="15" y1="18.2" x2="15.3" y2="21" />
    </Base>
  );
}

export function WheatIcon(props) {
  return (
    <Base {...props}>
      <line x1="12" y1="4" x2="12" y2="21" />
      <path d="M12 6c-2 0-3-1.4-3-3M12 6c2 0 3-1.4 3-3" />
      <path d="M12 10c-2 0-3-1.4-3-3M12 10c2 0 3-1.4 3-3" />
      <path d="M12 14c-2 0-3-1.4-3-3M12 14c2 0 3-1.4 3-3" />
    </Base>
  );
}

export function SparkleIcon(props) {
  return (
    <Base {...props}>
      <path d="M12 2.5 13.8 9.2 20.5 11 13.8 12.8 12 19.5 10.2 12.8 3.5 11 10.2 9.2Z" />
    </Base>
  );
}

export function CreatureIcon(props) {
  return (
    <Base {...props}>
      <circle cx="12" cy="13.5" r="6" />
      <path d="M7.5 8.5 6 4.5" />
      <path d="M16.5 8.5 18 4.5" />
      <circle cx="9.6" cy="12.5" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="14.4" cy="12.5" r="0.9" fill="currentColor" stroke="none" />
      <path d="M10 16c.7.6 3.3.6 4 0" />
    </Base>
  );
}
