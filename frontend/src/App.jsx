import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SupabaseProvider } from './contexts/SupabaseContext.jsx';
import DiceApp from './dice/App.jsx';

export default function App() {
  return (
    <SupabaseProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/dice/*" element={<DiceApp />} />
          <Route path="*" element={<Navigate replace to="/dice" />} />
        </Routes>
      </BrowserRouter>
    </SupabaseProvider>
  );
}
