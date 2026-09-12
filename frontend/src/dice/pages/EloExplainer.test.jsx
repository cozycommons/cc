import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import EloExplainer from './EloExplainer.jsx';


describe('EloExplainer', () => {
  it('explains the canonical confidence-based rating in plain language', () => {
    render(<MemoryRouter><EloExplainer /></MemoryRouter>);
    const copy = document.body.textContent;

    expect(copy).toMatch(/win ranked games and climb/i);
    expect(copy).toMatch(/normal games.*never move your ELO/i);
    expect(copy).toMatch(/beat a stronger team or win big and you earn more/i);
    expect(copy).toMatch(/no single game can blow up your rating/i);
    expect(copy).toMatch(/first 3 ranked games/i);
    expect(copy).toMatch(/settles as it gets more confident/i);
    expect(copy).toMatch(/long break never changes your ELO by itself/i);
    expect(copy).toMatch(/old result gets corrected.*rebuild the rankings/i);
    expect(copy).not.toMatch(/K-factor/i);
  });
});
