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
});
