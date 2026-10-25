import { lazy } from 'react';
import { recoverChunkLoad } from './chunkRecovery.js';

export function lazyWithRecovery(importer) {
  return lazy(() => importer().catch(error => {
    recoverChunkLoad(error);
    throw error;
  }));
}
