import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SupabaseProvider } from './contexts/SupabaseContext.jsx';
import CommonsHome from './commons/CommonsHome.jsx';
import DiceApp from './dice/App.jsx';

export default function App() {
  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <Routes>
        <Route path="/" element={<CommonsHome />} />
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
