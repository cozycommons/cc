import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import PlayerAvatar from './PlayerAvatar.jsx';

describe('PlayerAvatar', () => {
  it('uses a distinctive dice face instead of a letter-only fallback', () => {
    const { container } = render(
      <MemoryRouter><PlayerAvatar profile={{ user_id: 'alice', display_name: 'Alice' }} linkToProfile={false} /></MemoryRouter>,
    );
    expect(container.querySelector('svg')).toBeInTheDocument();
    expect(container.querySelectorAll('circle').length).toBeGreaterThan(1);
  });

  it('keeps uploaded profile photos as the primary identity', () => {
    const { container } = render(
      <MemoryRouter><PlayerAvatar profile={{ user_id: 'alice', display_name: 'Alice', avatar_url: '/alice.jpg' }} linkToProfile={false} /></MemoryRouter>,
    );
    expect(container.querySelector('img')).toHaveAttribute('src', '/alice.jpg');
    expect(container.querySelector('svg')).not.toBeInTheDocument();
  });
});
