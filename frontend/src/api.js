import { resolveRuntimeServiceUrl } from './runtimeConfig.js';

// Vite's `define` (see vite.config.js) inlines VITE_API_URL as a literal
// string at build time, so this is synchronous — no need to fetch
// config.json over the network before requests can be made.
function getUrl() {
  const apiUrl = resolveRuntimeServiceUrl(import.meta.env.VITE_API_URL);
  if (!apiUrl) {
    throw new Error('VITE_API_URL is missing');
  }
  return apiUrl;
}

function isTokenExpired(token) {
  if (!token) return true;

  if (typeof token !== 'string') return true;
  const parts = token.split('.');
  if (parts.length !== 3) return true;
  const payload = parts[1];
  if (!payload) return true;

  try {
    const decoded = JSON.parse(atob(payload));
    const exp = decoded.exp;
    if (!exp) return true;

    const now = Math.floor(Date.now() / 1000); // Current time in seconds
    return now >= exp;
  } catch (e) {
    return true; // Malformed token
  }
}

// Shared API utilities

class ApiClient {
  constructor() {
    this.apiUrlPromise = getUrl();
    this.listeners = {};
  }

  get(endpoint, idToken = null) {
    let options = {
      headers: {}
    }

    // Only add Authorization header if token is provided
    if (idToken) {
      options.headers.Authorization = `Bearer ${idToken}`;
    }

    return this.request('GET', endpoint, null, options);
  }

  post(endpoint, data, idToken = null) {
    let options = {
      headers: {
        Authorization: `Bearer ${idToken}`,
        'Content-Type': 'application/json',
      }
    }
    return this.request('POST', endpoint, data, options);
  }

  async request(method, endpoint, data = null, options = {}) {
    const base = await this.apiUrlPromise;
    const url = `${base}${endpoint}`;
    const headers = {
      ...(options.headers || {}),
    };
    const config = {
      method,
      headers,
      ...options,
    };

    if (data) {
      config.body = JSON.stringify(data);
    }

    const response = await fetch(url, config);
    if (!response.ok) {
      throw new Error(`API ${method} ${endpoint} failed: ${response.statusText}`);
    }
    return response.json();
  }

  // Subscribe to an event
  on(eventName, callback) {
    if (!(eventName in this.listeners)) {
      this.listeners[eventName] = [];
    }
    this.listeners[eventName].push(callback);
  }

  // Unsubscribe from an event
  off(eventName, callback) {
    if (!this.listeners[eventName]) return;

    this.listeners[eventName] = this.listeners[eventName].filter(fn => fn !== callback);
  }

}

export const api = new ApiClient();
export { isTokenExpired, getUrl };
