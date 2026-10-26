import React from 'react';
import { lazyWithRecovery } from './lazyWithRecovery.js';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
const RouteAnalytics = React.lazy(() => import('./analytics/RouteAnalytics.jsx'));
const SupabaseProvider = lazyWithRecovery(() => import('./contexts/LazySupabaseProvider.jsx'));
const CozyWabiLanding = lazyWithRecovery(() => import('./design/CozyWabiLanding.jsx'));
const Admin = React.lazy(() => import('./admin/Admin.jsx'));
const DiceApp = lazyWithRecovery(() => import('./dice/App.jsx'));

const Crowdset = lazyWithRecovery(() => import('./crowdset/Crowdset.jsx'));
const TripsApp = lazyWithRecovery(() => import('./trips/TripsApp.jsx'));
const Fantasy = lazyWithRecovery(() => import('./fantasy/Fantasy.jsx'));

const DesignIndex = lazyWithRecovery(() => import('./design/DesignIndex.jsx'));
const DiceDesignApp = lazyWithRecovery(() => import('../../design/dice/App.jsx'));

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
        <Route path="/trips/*" element={<React.Suspense fallback={<TripsSplash />}><SupabaseProvider><TripsApp /></SupabaseProvider></React.Suspense>} />
        <Route path="/fantasy/*" element={<React.Suspense fallback={null}><Fantasy /></React.Suspense>} />
        <Route path="/crowdset/:slug?" element={<React.Suspense fallback={<p>Opening Crowdset…</p>}><Crowdset /></React.Suspense>} />
        <Route path="/crowd-set" element={<LegacyCrowdsetRedirect />} />
        <Route path="/design" element={<React.Suspense fallback={null}><DesignIndex /></React.Suspense>} />
        <Route path="/design/dice" element={<React.Suspense fallback={null}><DiceDesignApp /></React.Suspense>} />
        <Route
          path="/dice/*"
          element={(
            <React.Suspense fallback={<p>Opening Dice…</p>}>
              <SupabaseProvider><DiceApp /></SupabaseProvider>
            </React.Suspense>
          )}
        />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}
