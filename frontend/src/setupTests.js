// jest-dom adds custom matchers for asserting on DOM nodes.
import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { invalidateDiceResources } from './dice/resourceCache.js';

// Lazy routes can exceed the 1000ms default when CI runs many projects together.
configure({ asyncUtilTimeout: 5000 });

// Dice pages share a module-level read cache; keep tests independent.
afterEach(() => invalidateDiceResources());

class MockIntersectionObserver {
  constructor() {}
  observe() {}
  unobserve() {}
  disconnect() {}
}

class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver = MockIntersectionObserver;
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = MockResizeObserver;
}

if (!globalThis.navigator.clipboard) {
  globalThis.navigator.clipboard = {
    writeText: vi.fn(),
  };
}

if (!globalThis.matchMedia) {
  globalThis.matchMedia = () => ({
    matches: false,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = () => {};
}

if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}

if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}

if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
