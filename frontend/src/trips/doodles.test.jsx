import React from 'react';
import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Bag, Bowl, Cabin, Camper, Ticket, TripStamp, nitehartsSticker, tripSticker, tripStickers } from './doodles.jsx';

afterEach(cleanup);

it('gives each trip a stable sticker and spreads trips across the set', () => {
  expect(tripSticker({ id: 'trip-a' })).toBe(tripSticker({ id: 'trip-a' }));
  const used = new Set(Array.from({ length: 40 }, (_, i) => tripSticker({ id: `trip-${i}` }).key));
  expect(used.size).toBeGreaterThan(4);
  expect(tripStickers.every((sticker) => /^#[0-9a-f]{6}$/i.test(sticker.cover))).toBe(true);
});

it('gives NITEHARTS its own sticker without reshuffling other trips', () => {
  expect(tripSticker({ id: 'trip-a', name: 'NITEHARTS 26' })).toBe(nitehartsSticker);
  expect(tripSticker({ id: 'trip-b', name: 'Niteharts' })).toBe(nitehartsSticker);
  expect(tripSticker({ id: 'trip-a', name: 'Tahoe' })).toBe(tripSticker({ id: 'trip-a' }));
});

it('keeps doodles decorative so labels carry the meaning', () => {
  const { container } = render(<>{[Bowl, Cabin, Camper, Ticket, Bag].map((Icon) => <Icon key={Icon.name} />)}<TripStamp trip={{ id: 'x' }} /><TripStamp trip={{ name: 'NITEHARTS 26' }} /></>);
  const svgs = container.querySelectorAll('svg');
  expect(svgs).toHaveLength(7);
  svgs.forEach((svg) => expect(svg.closest('[aria-hidden="true"]')).not.toBeNull());
});
