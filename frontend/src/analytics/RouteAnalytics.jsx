import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { projectForPath, trackEvent } from './events.js';

// Navigation identity survives StrictMode remounts but changes for back/forward entries.
let lastNavigation;
export default function RouteAnalytics() {
  const { pathname, key } = useLocation();
  useEffect(() => {
    const project = projectForPath(pathname);
    if (!project) { lastNavigation = null; return undefined; }
    const report = (eventType) => {
      if (document.visibilityState !== 'hidden') {
        void trackEvent({ project, path: pathname, eventType, eventName: `${project}.${eventType === 'pageview' ? 'page_viewed' : 'activity'}` });
      }
    };
    const navigation = `${key}:${pathname}`;
    if (lastNavigation !== navigation) { lastNavigation = navigation; report('pageview'); }
    const timer = setInterval(() => report('activity'), 5 * 60 * 1000);
    const visible = () => report('activity');
    document.addEventListener('visibilitychange', visible);
    let subscription;
    let disposed = false;
    import('../supabase.js').then(({ getClient }) => {
      if (disposed) return;
      let previous;
      subscription = getClient().auth.onAuthStateChange((_event, session) => {
        const identity = session?.user?.id || null;
        if (previous !== undefined && previous !== identity) setTimeout(() => report('activity'), 0);
        previous = identity;
      }).data.subscription;
    }).catch(() => { /* Local previews can lack auth configuration. */ });
    return () => { disposed = true; clearInterval(timer); document.removeEventListener('visibilitychange', visible); subscription?.unsubscribe(); };
  }, [pathname, key]);
  return null;
}
