import React from 'react';
import { Link } from 'react-router-dom';
import CozyMascot from './CozyMascot.jsx';
import './SiteHeader.css';

// Shared Cozy Commons navbar: mascot lockup, optional product wordmark, and a right-hand slot for account or admin controls.
export default function SiteHeader({ product, to, icon, children, onProductClick, productDisabled = false }) {
  return (
    <header className={`cc-sitebar${product ? ' cc-sitebar--product' : ''}`}>
      <Link to="/" className="cc-sitebar-home" aria-label="Cozy Commons home">
        <CozyMascot size={32} animated className="cc-sitebar-mascot" />
        <span className="cc-sitebar-name" aria-hidden="true">Cozy Commons</span>
      </Link>
      {product && (
        <Link to={to} className="cc-sitebar-wordmark" aria-disabled={productDisabled || undefined} onClick={(event) => {
          if (productDisabled) { event.preventDefault(); return; }
          onProductClick?.(event);
        }}>
          {icon && <span className="cc-sitebar-logo" aria-hidden="true">{icon}</span>}{product}
        </Link>
      )}
      {children && <div className="cc-sitebar-end">{children}</div>}
    </header>
  );
}
