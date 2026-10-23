// Local Trips preview only. The shared Vite/Dice sandbox guards stay unchanged.
import { defineConfig, mergeConfig } from 'vite';
import sharedConfig from './vite.config.js';

export default defineConfig((environment) => {
  if (environment.mode === 'production' || process.env.COZY_TRIPS_LOCAL !== '1') {
    throw new Error('Use the normal Vite config for production. Trips preview is local-only.');
  }
  return mergeConfig(sharedConfig(environment), {
    define: { 'import.meta.env.VITE_TRIPS_LOCAL_DEMO': JSON.stringify('true') },
    server: {
      host: '127.0.0.1', port: 8815, strictPort: true,
      allowedHosts: ['localhost', '127.0.0.1', 'desktop-r5cm15p.tail9170c8.ts.net'],
      headers: { 'Referrer-Policy': 'no-referrer' },
      proxy: {
        '^/api/(trips|dice)(?:/|$)': {
          target: 'http://127.0.0.1:8011',
          rewrite: (url) => url.replace(/^\/api/, ''),
        },
        '^/api/(health|ready)$': {
          target: 'http://127.0.0.1:8011',
          rewrite: (url) => url.replace(/^\/api/, ''),
        },
        '^/(auth|rest|storage)/v1': { target: 'http://127.0.0.1:55321', changeOrigin: true },
      },
    },
  });
});
