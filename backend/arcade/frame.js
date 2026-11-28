/* Movie compatibility is confined to this frame and its installed package. */
const status = document.querySelector('#status');
// Allowed embedding origins are supplied by the server, not by any message.
const parents = __PARENT_ORIGINS__;
// Until a Commons page launches the game, a message is delivered only if the
// parent is one of the allowed origins; afterwards only to that page's origin.
const ancestor = location.ancestorOrigins?.[0];
let commons = parents.includes(ancestor) ? ancestor : null;
const send = (type, extra = {}) => {for (const origin of commons ? [commons] : parents) parent.postMessage({type, ...extra}, origin);};
let started = false;
let finished = false;
// Extra keys and gamepad buttons press the key the game already uses for that
// action. The launch carries the resolved bindings (backend/arcade/controls.py).
// Registered before Ruffle loads so the capture listener runs first.
const bindInput = ({targets, keys, buttons}) => {
  let gameTarget = null; // Ruffle listens inside its shadow root, not on the host.
  const held = {}; // action -> number of extra inputs holding it
  const deepestFocus = () => {
    let element = document.activeElement;
    while (element?.shadowRoot?.activeElement) element = element.shadowRoot.activeElement;
    return element || document.body;
  };
  const press = (type, action, repeat = false) => {
    const target = targets[action];
    if (!target) return;
    if (!repeat) {
      held[action] = Math.max(0, (held[action] || 0) + (type === 'keydown' ? 1 : -1));
      // Another input still holds this action, or it was already down.
      if (type === 'keyup' ? held[action] > 0 : held[action] > 1) return;
    }
    const event = new KeyboardEvent(type, {code: target.code, key: target.key, bubbles: true,
      cancelable: true, composed: true, repeat});
    // KeyboardEvent ignores keyCode/which in its init dictionary; Flash games read them.
    for (const name of ['keyCode', 'which']) Object.defineProperty(event, name, {get: () => target.key_code});
    (gameTarget?.isConnected ? gameTarget : deepestFocus()).dispatchEvent(event);
  };
  for (const type of ['keydown', 'keyup']) {
    addEventListener(type, event => {
      if (!event.isTrusted) return;
      gameTarget = event.composedPath()[0];
      const action = keys[event.code];
      if (!action) return;
      event.preventDefault(); event.stopImmediatePropagation();
      press(type, action, event.repeat);
    }, true);
  }
  if (!Object.keys(buttons).length || !navigator.getGamepads) return;
  // The left stick doubles as the d-pad (standard buttons 12-15).
  const stick = (pad, axis, sign) => sign * (pad.axes[axis] || 0) > 0.5;
  const pressed = pad => button => pad.buttons[button]?.pressed ||
    (button === 12 && stick(pad, 1, -1)) || (button === 13 && stick(pad, 1, 1)) ||
    (button === 14 && stick(pad, 0, -1)) || (button === 15 && stick(pad, 0, 1));
  const down = new Set(); // "pad:button" currently held
  const poll = () => {
    const now = new Set();
    for (const pad of navigator.getGamepads()) {
      if (!pad?.connected) continue;
      const isDown = pressed(pad);
      for (const button of Object.keys(buttons)) if (isDown(Number(button))) now.add(pad.index + ':' + button);
    }
    for (const id of now) if (!down.has(id)) press('keydown', buttons[id.split(':')[1]]);
    for (const id of down) if (!now.has(id)) press('keyup', buttons[id.split(':')[1]]);
    down.clear(); for (const id of now) down.add(id);
    requestAnimationFrame(poll);
  };
  requestAnimationFrame(poll);
};
const finish = () => {if (!finished) {finished = true; send('arcade-result');}};
addEventListener('message', async event => {
  if (event.source !== parent || event.origin === 'null' || started || event.data?.type !== 'arcade-launch') return;
  if (!parents.includes(event.origin)) return;
  started = true; commons = event.origin;
  const {launch, settings} = event.data;
  try {
    bindInput(launch.input);
    const player = window.RufflePlayer.newest().createPlayer();
    const base = new URL('.', location.href).href.replace(/\/$/, '');
    // Ruffle's ExternalInterface uses eval, which this frame deliberately disallows.
    // Observe the successful record acknowledgement without reading protocol bodies.
    const fetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await fetch(...args);
      if (response.ok && response.url === base + '/compat/api' && response.headers.get('X-Arcade-Run') === 'finished') finish();
      return response;
    };
    const rules = Object.entries(launch.origins).map(([origin, alias]) => [
      new RegExp('^https?://' + origin.replace(/[.*+?^$()|[\]\\]/g, '\\$&') + '/'),
      base + '/assets/' + alias + '/'
    ]);
    for (const origin of Object.keys(launch.origins)) {
      rules.unshift([new RegExp('^https?://' + origin.replace(/[.*+?^$()|[\]\\]/g, '\\$&') + '/api(?:[?].*)?$'), base + '/compat/api']);
    }
    // Untrusted movies get no ExternalInterface (Ruffle installs it only with script
    // access and full networking) and no URL navigation. URLLoader, sockets and
    // loads stay available, fenced by this frame's connect-src.
    const trusted = launch.trusted === true;
    player.config = {publicPath: base + '/player/', autoplay: 'on', splashScreen: false,
      contextMenu: 'off', openUrlMode: 'deny', urlRewriteRules: rules,
      ...(launch.frame_rate ? {frameRate: launch.frame_rate} : {}),
      allowScriptAccess: trusted, allowNetworking: trusted ? 'all' : 'internal',
      unmuteOverlay: 'hidden', volume: settings.sound ? 1 : 0};
    // Names are imported from the legacy page into the private package.
    for (const [name, kind] of trusted ? Object.entries(launch.callbacks) : []) {
      window[name] = (...args) => {
        if (kind === 'result') finish();
        if (kind === 'error') { status.textContent = 'The game could not continue.'; send('arcade-error'); }
      };
    }
    document.querySelector('#game').append(player);
    await player.ruffle().load({url: base + '/assets/' + launch.entry,
      parameters: {sessionId: encodeURIComponent(launch.session), sessionToken: '', loginId: '1',
        startParam: 'play', isForceLogin: 'true', isDemo: '', ip: '', externalId: launch.session,
        channelId: '0', timestamp: '0', numGamesToPlayAd: '0', isPrerollEnabled: 'false',
        isAnalyticsEnabled: 'false', apiUrl: encodeURIComponent(base + '/compat/api'), showChallenge: '0',
        prerollId: '-1', foeUserIds: '', blockedToByUserIds: '', theGamePath: ''}});
    status.textContent = '';
    player.focus();
  } catch {
    status.textContent = 'Unable to load the game package.';
    send('arcade-error');
  }
});
addEventListener('load', () => send('arcade-ready'));
