import React, { useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import AccountMenu from './AccountMenu.jsx';
import CozyMascot from './CozyMascot.jsx';
import './SiteHeader.css';

// BrowserRouter records each entry's position in history.state.idx: 0 for the
// first page of this visit, and still 0 after a replace. A plain #anchor link
// (such as a skip link) adds an entry with no state, so navigations seen while
// the header is mounted count too. MemoryRouter (tests) has no state; its first
// entry has the key "default".
function hasInAppHistory(location, navigatedWhileMounted) {
  const index = typeof window !== 'undefined' ? window.history.state?.idx : undefined;
  if (typeof index === 'number') return index > 0;
  return navigatedWhileMounted || location.key !== 'default';
}

function normalizePath(path) {
  return path.length > 1 ? path.replace(/\/+$/, '') : path;
}

// One back control for every product. It steps back through in-app history
// (including query-string views such as tabs); a page opened directly, from a
// shared link or a new tab, goes to its parent instead of leaving the site.
function BackButton({ home, fallback, disabled }) {
  const navigate = useNavigate();
  const location = useLocation();
  const firstKey = useRef(location.key);
  const navigated = useRef(false);
  useEffect(() => {
    if (location.key !== firstKey.current) navigated.current = true;
  }, [location.key]);
  if (normalizePath(location.pathname) === normalizePath(home)) return null;
  const goBack = () => {
    if (hasInAppHistory(location, navigated.current)) {
      navigate(-1);
      return;
    }
    const parent = typeof fallback === 'function' ? fallback(location.pathname, location.search) : fallback;
    navigate(parent || home, { replace: true });
  };
  return (
    <button type="button" className="cc-sitebar-icon cc-sitebar-back" onClick={goBack} disabled={disabled} aria-label="Back" title="Back">
      <ArrowLeft size={20} aria-hidden="true" />
    </button>
  );
}

// Shared Cozy Commons navbar: a back button, the mascot with an optional
// product sticker, a right-hand slot for product controls, and the signed-in
// person's avatar. Products get identity for free; `accountItems` adds their
// own links to the account menu and `onSignIn` (or `null`) changes sign-in.
//
// Products get the back button by default on every page below their home
// (`to`). `back={false}` opts a product or page out; `backFallback` (a path, or
// `(pathname, search) => path`) picks where it goes when there is no earlier
// in-app page, defaulting to the product home. It is disabled with the product link.
export default function SiteHeader({
  product, to, icon, children, onProductClick, productDisabled = false, back = true, backFallback,
  accountItems, onSignIn,
}) {
  return (
    <header className={`cc-sitebar${product ? ' cc-sitebar--product' : ''}`}>
      {/* One lockup: the mascot, then the product's sticker and name. */}
      <div className="cc-sitebar-lockup">
        {product && to && back && <BackButton home={to} fallback={backFallback} disabled={productDisabled} />}
        <Link to="/" className="cc-sitebar-home" aria-label="Cozy Commons home">
          {/* The site has no dark theme, so the header keeps the light palette in every colour scheme. */}
          <CozyMascot size={32} tone="light" animated className="cc-sitebar-mascot" />
        </Link>
        {product && (
          <Link to={to} className={`cc-sitebar-wordmark${icon ? ' cc-sitebar-wordmark--icon' : ''}`} aria-disabled={productDisabled || undefined} onClick={(event) => {
              if (productDisabled) { event.preventDefault(); return; }
              onProductClick?.(event);
            }}>
            {icon && <span className="cc-sitebar-logo" aria-hidden="true">{icon}</span>}{product}
          </Link>
        )}
      </div>
      <div className="cc-sitebar-end">{children}
        <AccountMenu items={accountItems} onSignIn={onSignIn} />
      </div>
    </header>
  );
}
