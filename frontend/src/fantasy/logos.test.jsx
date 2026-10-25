import React from 'react';
import { fireEvent, render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TeamLogo } from './parts.jsx';

describe('lazy team logos', () => {
  it('shows initials immediately and swaps in the decoded image on load', () => {
    const { container } = render(<TeamLogo team={{ name: 'Harbor Hoopers', logo: '/logo.png' }} side={0} />);
    expect(container.textContent).toBe('HH');
    const image = container.querySelector('img');
    expect(image).toHaveAttribute('loading', 'lazy');
    expect(image).toHaveAttribute('decoding', 'async');
    expect(image.style.opacity).toBe('0');
    fireEvent.load(image);
    expect(image.style.opacity).toBe('1');
  });

  it('keeps initials on failure and can load a changed logo', () => {
    const { container, rerender } = render(<TeamLogo team={{ name: 'Harbor Hoopers', logo: '/old.png' }} side={0} />);
    fireEvent.error(container.querySelector('img'));
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toBe('HH');
    rerender(<TeamLogo team={{ name: 'Harbor Hoopers', logo: '/new.png' }} side={0} />);
    expect(container.querySelector('img')).toHaveAttribute('src', '/new.png');
    expect(container.querySelector('img').style.opacity).toBe('0');
  });
});
