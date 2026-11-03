const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

for (const enabled of [false, true]) {
  test(`onboarding sends automation=${enabled} atomically`, async () => {
    const elements = new Map();
    const element = (id) => {
      if (!elements.has(id)) elements.set(id, {
        value: '', checked: enabled, style: {},
        addEventListener(event, handler) { this[event] = handler; },
      });
      return elements.get(id);
    };
    element('league').value = '111';
    element('season').value = '2027';
    const calls = [];
    const context = vm.createContext({
      document: { getElementById: element },
      chrome: { cookies: {
        getAllCookieStores: async () => [],
        getAll: async () => [], get: async () => null,
      } },
      fetch: async (url, options) => {
        calls.push({ url, body: JSON.parse(options.body) });
        return { ok: true, json: async () => ({
          id: 'synthetic', league_id: 111, token: 'test-token',
          lineup_automation_enabled: enabled,
        }) };
      },
    });
    vm.runInContext(readFileSync(`${__dirname}/popup.js`, 'utf8'), context);
    await element('connect').click();
    assert.equal(calls[0].body.enable_automation, enabled);
    assert.equal(calls.length, 1, 'no separate post-creation enable request');
    assert.match(element('status').textContent,
      new RegExp(`Automatic lineups: ${enabled ? 'enabled' : 'disabled'}`));
  });
}
