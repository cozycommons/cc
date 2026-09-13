import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SupabaseProvider } from './contexts/SupabaseContext.jsx';
import CommonsHome from './commons/CommonsHome.jsx';
import CommonsScenePage from './commons/CommonsScenePage.jsx';
import DesignIndex from './design/DesignIndex.jsx';
import DiceApp from './dice/App.jsx';
import DiceDesignApp from '../../design/dice/App.jsx';

export default function App() {
  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <Routes>
        <Route path="/" element={<CommonsHome />} />
        <Route path="/scene" element={<CommonsScenePage />} />
        <Route path="/design" element={<DesignIndex />} />
        <Route path="/design/dice" element={<DiceDesignApp />} />
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
