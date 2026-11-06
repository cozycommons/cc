import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Conditions from './Conditions.jsx';

describe('conditions', () => {
  it('says why this hour is unusual and passes on Citi Bike alerts', () => {
    render(<Conditions conditions={{
      note: 'Heavy rain, 12°C: about 58% fewer trips than usual, so refills are slower.',
      weather: { sky: 'heavy rain', temp_c: 12, snow_72h_cm: 0 }, alerts: [{ summary: 'Service paused for the storm.' }],
    }} />);
    expect(screen.getByText(/^Heavy rain, 12°C/)).toBeTruthy();
    expect(screen.getByText('Service paused for the storm.')).toBeTruthy();
  });

  it('stays quiet on an ordinary hour', () => {
    const { container } = render(<Conditions conditions={{ note: null, alerts: [], weather: { sky: 'dry', temp_c: 17 } }} />);
    expect(container.textContent).toBe('');
  });
});
