import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import CozyWabiLanding from './CozyWabiLanding.jsx';

describe('home shelf', () => {
  it('links every project, Bikes included', () => {
    render(<MemoryRouter><CozyWabiLanding /></MemoryRouter>);
    const links = screen.getAllByRole('link').map((a) => a.getAttribute('href'));
    for (const path of ['/dice', '/crowdset', '/fantasy', '/trips', '/bikes', '/floor-planner']) expect(links).toContain(path);
  });
});
