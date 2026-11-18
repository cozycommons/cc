import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Bouquet from './Bouquet.jsx';

describe('Bouquet page', () => {
  it('renders the bouquet with its dedication for Laura', () => {
    render(<Bouquet />);
    expect(screen.getByRole('heading', { name: 'for Laura' })).toBeTruthy();
    expect(screen.getByText('grown in code, so they never wilt')).toBeTruthy();
    expect(screen.getByRole('img', { name: /bouquet of roses, tulips, daisies/i })).toBeTruthy();
  });

  it('keeps bloom animation and positioning on separate elements', () => {
    const { container } = render(<Bouquet />);
    // A CSS transform animation overrides the SVG transform attribute on the
    // same element, discarding the flower's position — so no animated group
    // may carry a positioning transform itself.
    const animated = container.querySelectorAll('g.bq-bloom');
    expect(animated.length).toBeGreaterThan(0);
    animated.forEach((g) => expect(g.getAttribute('transform')).toBeNull());
    // Every flower head (9 blooms + 3 baby's-breath sprays) is instead placed
    // by an outer translate group wrapping its animated group.
    const positioned = container.querySelectorAll('g[transform^="translate"]');
    expect(positioned.length).toBe(12);
    positioned.forEach((g) => expect(g.querySelector(':scope > g.bq-bloom')).toBeTruthy());
  });
});
