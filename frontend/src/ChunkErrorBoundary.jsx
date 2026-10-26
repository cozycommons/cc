import React from 'react';
import { recoverChunkLoad } from './chunkRecovery.js';

export default class ChunkErrorBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error) { recoverChunkLoad(error); }
  render() {
    return this.state.failed
      ? <p role="alert">This page couldn’t load. Please try again later.</p>
      : this.props.children;
  }
}
