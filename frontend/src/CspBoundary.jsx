import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { documentKind } from '../csp.js';

export default function CspBoundary({ children, reload = () => window.location.reload() }) {
  const { pathname } = useLocation();
  const [documentKindAtLoad] = useState(() => documentKind(window.location.pathname));
  const crossing = documentKindAtLoad !== documentKind(pathname);
  useEffect(() => { if (crossing) reload(); }, [crossing, reload]);
  // HTTP policy belongs to the document, not the current history entry. Never
  // mount a credential form in a document loaded with the general policy, and
  // load Crowdset from the server that owns it (with its own policy).
  return crossing ? null : children;
}
