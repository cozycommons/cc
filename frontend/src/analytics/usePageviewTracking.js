import { useEffect } from 'react';
import { trackPageview } from './trackPageview.js';

// Fires once per mount -- put this in the top-level component of any route
// that should be logged as a page view (see backend/analytics.py /pageview).
export function usePageviewTracking(app, label, path) {
  useEffect(() => {
    trackPageview({ app, label, path });
  }, [app, label, path]);
}
