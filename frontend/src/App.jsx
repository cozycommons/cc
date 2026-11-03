import React from 'react';
import { lazyWithRecovery } from './lazyWithRecovery.js';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
const RouteAnalytics = React.lazy(() => import('./analytics/RouteAnalytics.jsx'));
const SupabaseProvider = lazyWithRecovery(() => import('./contexts/LazySupabaseProvider.jsx'));
// One shared import per chunk, used by both the route preload and the lazy
// component; a failed load is forgotten so the next attempt can retry.
function sharedImport(importer) {
  let pending = null;
  return () => {
    pending ??= importer().catch((error) => {
      pending = null;
      throw error;
    });
    return pending;
  };
}
const loadDiceApp = sharedImport(() => import('./dice/App.jsx'));
const loadTripsApp = sharedImport(() => import('./trips/TripsApp.jsx'));
const loadFloorPlannerApp = sharedImport(() => import('./floor-planner/App.jsx'));
const CozyWabiLanding = lazyWithRecovery(() => import('./design/CozyWabiLanding.jsx'));
const Admin = React.lazy(() => import('./admin/Admin.jsx'));
const DiceApp = lazyWithRecovery(loadDiceApp);

const Crowdset = lazyWithRecovery(() => import('./crowdset/Crowdset.jsx'));
const TripsApp = lazyWithRecovery(loadTripsApp);
const Fantasy = lazyWithRecovery(() => import('./fantasy/Fantasy.jsx'));
const FloorPlannerApp = lazyWithRecovery(loadFloorPlannerApp);
const OAuthConsent = lazyWithRecovery(() => import('./auth/OAuthConsent.jsx'));

const DesignIndex = lazyWithRecovery(() => import('./design/DesignIndex.jsx'));
const DiceDesignApp = lazyWithRecovery(() => import('../../design/dice/App.jsx'));

// The app chunk would otherwise only start downloading after the lazy Supabase
// provider resolves and renders it; start both together. Load errors surface
// (and recover) through the lazy component itself.
function PreloadedSupabaseRoute({ load, children }) {
  load().catch(() => {});
  return <SupabaseProvider>{children}</SupabaseProvider>;
}

function LegacyCrowdsetRedirect() {
  const { search, hash } = useLocation();
  return <Navigate replace to={`/crowdset${search}${hash}`} />;
}

// Shown before the Trips bundle (and its stylesheet) arrives, so it carries its own paper colours.
const TripsSplash = () => <p role="status" style={{ boxSizing: 'border-box', minHeight: '100svh', margin: 0, padding: '28px 24px',
  background: '#e7dcc5', color: '#6f6256', font: '15px/1.5 system-ui, -apple-system, sans-serif' }}>Opening Cozy Trips…</p>;

export default function App() {
  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <React.Suspense fallback={null}><RouteAnalytics /></React.Suspense>
      <Routes>
        <Route path="/admin/*" element={<React.Suspense fallback={<p>Loading…</p>}><Admin /></React.Suspense>} />
        <Route path="/" element={<React.Suspense fallback={null}><CozyWabiLanding /></React.Suspense>} />
        <Route path="/trips/*" element={<React.Suspense fallback={<TripsSplash />}><PreloadedSupabaseRoute load={loadTripsApp}><TripsApp /></PreloadedSupabaseRoute></React.Suspense>} />
        <Route path="/floor-planner/*" element={<React.Suspense fallback={<p>Opening Floor Planner…</p>}><PreloadedSupabaseRoute load={loadFloorPlannerApp}><FloorPlannerApp /></PreloadedSupabaseRoute></React.Suspense>} />
        <Route path="/oauth/consent" element={<React.Suspense fallback={<p>Loading connection request…</p>}><SupabaseProvider><OAuthConsent /></SupabaseProvider></React.Suspense>} />
        <Route path="/fantasy/*" element={<React.Suspense fallback={null}><Fantasy /></React.Suspense>} />
        <Route path="/crowdset/:slug?" element={<React.Suspense fallback={<p>Opening Crowdset…</p>}><Crowdset /></React.Suspense>} />
        <Route path="/crowd-set" element={<LegacyCrowdsetRedirect />} />
        <Route path="/design" element={<React.Suspense fallback={null}><DesignIndex /></React.Suspense>} />
        <Route path="/design/dice" element={<React.Suspense fallback={null}><DiceDesignApp /></React.Suspense>} />
        <Route
          path="/dice/*"
          element={(
            <React.Suspense fallback={<p>Opening Dice…</p>}>
              <PreloadedSupabaseRoute load={loadDiceApp}><DiceApp /></PreloadedSupabaseRoute>
            </React.Suspense>
          )}
        />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}
