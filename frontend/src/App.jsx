import React from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { SupabaseProvider } from './contexts/SupabaseContext.jsx';
import CozyWabiLanding from './design/CozyWabiLanding.jsx';
const DiceApp = React.lazy(() => import('./dice/App.jsx'));

const Crowdset = React.lazy(() => import('./crowdset/Crowdset.jsx'));
const TripsApp = React.lazy(() => import('./trips/TripsApp.jsx'));
const Fantasy = React.lazy(() => import('./fantasy/Fantasy.jsx'));

const DesignIndex = React.lazy(() => import('./design/DesignIndex.jsx'));
const DiceDesignApp = React.lazy(() => import('../../design/dice/App.jsx'));

function LegacyCrowdsetRedirect() {
  const { search, hash } = useLocation();
  return <Navigate replace to={`/crowdset${search}${hash}`} />;
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <Routes>
        <Route path="/" element={<CozyWabiLanding />} />
        <Route path="/trips/*" element={<SupabaseProvider><React.Suspense fallback={<p>Opening Cozy Trips…</p>}><TripsApp /></React.Suspense></SupabaseProvider>} />
        <Route path="/fantasy/*" element={<React.Suspense fallback={null}><Fantasy /></React.Suspense>} />
        <Route path="/crowdset/:slug?" element={<React.Suspense fallback={<p>Opening Crowdset…</p>}><Crowdset /></React.Suspense>} />
        <Route path="/crowd-set" element={<LegacyCrowdsetRedirect />} />
        <Route path="/design" element={<React.Suspense fallback={null}><DesignIndex /></React.Suspense>} />
        <Route path="/design/dice" element={<React.Suspense fallback={null}><DiceDesignApp /></React.Suspense>} />
        <Route
          path="/dice/*"
          element={(
            <SupabaseProvider>
              <React.Suspense fallback={<p>Opening Dice…</p>}><DiceApp /></React.Suspense>
            </SupabaseProvider>
          )}
        />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}
