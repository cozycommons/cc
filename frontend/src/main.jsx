import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ChunkErrorBoundary from './ChunkErrorBoundary.jsx'
import { installChunkRecovery } from './chunkRecovery.js'

installChunkRecovery()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ChunkErrorBoundary><App /></ChunkErrorBoundary>
  </React.StrictMode>,
)
