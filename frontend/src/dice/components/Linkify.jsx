import React from 'react';

const URL_PATTERN = /(https?:\/\/[^\s]+)/g;

// Renders plain text, turning any http(s) URLs into clickable links.
// Splits on the URL pattern and keeps every other captured group as a link.
export default function Linkify({ text }) {
  const parts = text.split(URL_PATTERN);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <a
        key={i}
        href={part}
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: 'var(--accent-secondary)', textDecoration: 'underline' }}
      >
        {part}
      </a>
    ) : (
      part
    )
  );
}
