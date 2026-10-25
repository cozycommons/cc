import React from 'react';
import { Link } from 'react-router-dom';
import './SiteHeader.css';

// Shared Cozy Commons navbar: home mark, product wordmark, and a right-hand slot for account or admin controls.
export default function SiteHeader({ product, to, icon, children }) {
  return (
    <header className="cc-sitebar">
      <Link to="/" className="cc-sitebar-home" aria-label="Cozy Commons home">
        <span className="cc-sitebar-mark" aria-hidden="true"><span>cozy</span><small>commons</small></span>
      </Link>
      <Link to={to} className="cc-sitebar-wordmark">
        {icon && <span className="cc-sitebar-logo" aria-hidden="true">{icon}</span>}{product}
      </Link>
      {children && <div className="cc-sitebar-end">{children}</div>}
    </header>
  );
}
