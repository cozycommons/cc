/* Movie compatibility is confined to this frame and its installed package. */
const status = document.querySelector('#status');
const send = (type, extra = {}) => parent.postMessage({type, ...extra}, '*');
let started = false;
addEventListener('message', async event => {
  if (event.source !== parent || event.origin === 'null' || started || event.data?.type !== 'arcade-launch') return;
  // Allowed embedding origins are supplied by the server, not by the message.
  if (!__PARENT_ORIGINS__.includes(event.origin)) return;
  started = true;
  const {launch, settings} = event.data;
  try {
    const remaps = Object.fromEntries(Object.entries(settings.keys).map(([action, code]) => [code, action]));
    const names = {8:'Backspace',9:'Tab',13:'Enter',16:'ShiftLeft',17:'ControlLeft',18:'AltLeft',
      27:'Escape',32:'Space',37:'ArrowLeft',38:'ArrowUp',39:'ArrowRight',40:'ArrowDown',
      186:'Semicolon',187:'Equal',188:'Comma',189:'Minus',190:'Period',191:'Slash',
      192:'Backquote',219:'BracketLeft',220:'Backslash',221:'BracketRight',222:'Quote'};
    const defaults = {left:37,right:39,soft:40,hard:32,cw:88,ccw:90,hold:67};
    const targets = Object.fromEntries(Object.entries(launch.controls || defaults).map(([action, id]) => [
      action, [names[id] || (id >= 65 && id <= 90 ? 'Key' + String.fromCharCode(id) :
        id >= 48 && id <= 57 ? 'Digit' + String.fromCharCode(id) : 'Unidentified'), id]
    ]));
    for (const type of ['keydown', 'keyup']) {
      addEventListener(type, event => {
        if (!event.isTrusted || !remaps[event.code]) return;
        const [code, keyCode] = targets[remaps[event.code]];
        event.preventDefault(); event.stopImmediatePropagation();
        const target = event.composedPath()[0];
        target.dispatchEvent(new KeyboardEvent(type, {code, key: code.startsWith('Key') ? code.slice(3).toLowerCase() : code,
          keyCode, which: keyCode, bubbles: true, composed: true, repeat: event.repeat}));
      }, true);
    }
    const player = window.RufflePlayer.newest().createPlayer();
    const base = new URL('.', location.href).href.replace(/\/$/, '');
    const rules = Object.entries(launch.origins).map(([origin, alias]) => [
      new RegExp('^https?://' + origin.replace(/[.*+?^$()|[\]\\]/g, '\\$&') + '/'),
      base + '/assets/' + alias + '/'
    ]);
    for (const origin of Object.keys(launch.origins)) {
      rules.unshift([new RegExp('^https?://' + origin.replace(/[.*+?^$()|[\]\\]/g, '\\$&') + '/api(?:[?].*)?$'), base + '/compat/api']);
    }
    player.config = {publicPath: base + '/player/', autoplay: 'on', splashScreen: false,
      contextMenu: 'off', openUrlMode: 'deny', urlRewriteRules: rules,
      ...(launch.frame_rate ? {frameRate: launch.frame_rate} : {}),
      allowScriptAccess: true, unmuteOverlay: 'hidden', volume: settings.sound ? 1 : 0};
    // Names are imported from the legacy page into the private package.
    for (const [name, kind] of Object.entries(launch.callbacks)) {
      window[name] = (...args) => {
        if (kind === 'result') send('arcade-result');
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
