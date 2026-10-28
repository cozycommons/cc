import React from 'react';
import { Link } from 'react-router-dom';
import CozyMascot from './CozyMascot.jsx';
import './SiteHeader.css';

// Shared Cozy Commons navbar: mascot with an optional product sticker, and a right-hand slot for account or admin controls.
export default function SiteHeader({ product, to, icon, children, onProductClick, productDisabled = false }) {
  return (
    <header className={`cc-sitebar${product ? ' cc-sitebar--product' : ''}`}>
      {/* One lockup: the mascot, with the product's icon beside it as its sticker. */}
      <div className="cc-sitebar-lockup">
        <Link to="/" className="cc-sitebar-home" aria-label="Cozy Commons home">
          {/* The site has no dark theme, so the header keeps the light palette in every colour scheme. */}
          <CozyMascot size={32} tone="light" animated className="cc-sitebar-mascot" />
        </Link>
        {product && (
          <Link to={to} className={`cc-sitebar-wordmark${icon ? ' cc-sitebar-wordmark--icon' : ''}`} aria-label={icon ? product : undefined} title={icon ? product : undefined}
            aria-disabled={productDisabled || undefined} onClick={(event) => {
              if (productDisabled) { event.preventDefault(); return; }
              onProductClick?.(event);
            }}>
            {icon ? <span className="cc-sitebar-logo" aria-hidden="true">{icon}</span> : product}
          </Link>
        )}
      </div>
      {children && <div className="cc-sitebar-end">{children}</div>}
    </header>
  );
}
