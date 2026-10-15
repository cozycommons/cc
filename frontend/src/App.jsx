import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SupabaseProvider } from './contexts/SupabaseContext.jsx';
import CommonsHome from './commons/CommonsHome.jsx';
import CommonsScenePage from './commons/CommonsScenePage.jsx';
import DiceApp from './dice/App.jsx';

const CrowdSet = React.lazy(() => import('./crowd-set/CrowdSet.jsx'));

const DesignIndex = React.lazy(() => import('./design/DesignIndex.jsx'));
const DiceDesignApp = React.lazy(() => import('../../design/dice/App.jsx'));

export default function App() {
  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <Routes>
        <Route path="/" element={<CommonsHome />} />
        <Route path="/crowd-set" element={<React.Suspense fallback={<p>Opening Crowd Set…</p>}><CrowdSet /></React.Suspense>} />
        <Route path="/scene" element={<CommonsScenePage />} />
        <Route path="/design" element={<React.Suspense fallback={null}><DesignIndex /></React.Suspense>} />
        <Route path="/design/dice" element={<React.Suspense fallback={null}><DiceDesignApp /></React.Suspense>} />
        <Route
          path="/dice/*"
          element={(
            <SupabaseProvider>
              <DiceApp />
            </SupabaseProvider>
          )}
        />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}
