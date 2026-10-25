import React from 'react';

export default function Basketball({ size = 16 }) {
  return (
    <svg viewBox="0 0 20 20" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="10" cy="10" r="7.5" /><path d="M2.5 10h15M10 2.5v15M4.7 4.7c2.6 2.6 2.6 8 0 10.6M15.3 4.7c-2.6 2.6-2.6 8 0 10.6" />
    </svg>
  );
}
