import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { credentialPage } from '../csp.js';

export default function CspBoundary({ children, reload = () => window.location.reload() }) {
  const { pathname } = useLocation();
  const [documentIsCredentialPage] = useState(() => credentialPage(window.location.pathname));
  const crossing = documentIsCredentialPage !== credentialPage(pathname);
  useEffect(() => { if (crossing) reload(); }, [crossing, reload]);
  // HTTP policy belongs to the document, not the current history entry. Never
  // mount a credential form in a document loaded with the general policy.
  return crossing ? null : children;
}
