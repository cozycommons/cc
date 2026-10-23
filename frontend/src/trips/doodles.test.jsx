import React from 'react';
import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Bag, Bowl, Cabin, Camper, Ticket, TripStamp, tripSticker, tripStickers } from './doodles.jsx';

afterEach(cleanup);

it('gives each trip a stable sticker and spreads trips across the set', () => {
  expect(tripSticker({ id: 'trip-a' })).toBe(tripSticker({ id: 'trip-a' }));
  const used = new Set(Array.from({ length: 40 }, (_, i) => tripSticker({ id: `trip-${i}` }).key));
  expect(used.size).toBeGreaterThan(4);
  expect(tripStickers.every((sticker) => /^#[0-9a-f]{6}$/i.test(sticker.cover))).toBe(true);
});

it('keeps doodles decorative so labels carry the meaning', () => {
  const { container } = render(<>{[Bowl, Cabin, Camper, Ticket, Bag].map((Icon) => <Icon key={Icon.name} />)}<TripStamp trip={{ id: 'x' }} /></>);
  const svgs = container.querySelectorAll('svg');
  expect(svgs).toHaveLength(6);
  svgs.forEach((svg) => expect(svg.closest('[aria-hidden="true"]')).not.toBeNull());
});
