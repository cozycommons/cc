const page = document.querySelector('[data-page]');
const lampSwitch = document.querySelector('[data-lamp-switch]');
const lampLabel = document.querySelector('[data-lamp-label]');
const globalStatus = document.querySelector('[data-global-status]');
const footerStatus = document.querySelector('[data-footer-status]');

function setLampState(isOn) {
  if (!page || !lampSwitch || !lampLabel || !globalStatus || !footerStatus) return;

  page.classList.toggle('lamp-off', !isOn);
  lampSwitch.setAttribute('aria-pressed', String(isOn));
  lampSwitch.setAttribute('aria-label', isOn ? 'Turn ambient light off' : 'Turn ambient light on');
  lampLabel.textContent = isOn ? 'on' : 'off';
  globalStatus.textContent = isOn ? 'the room is quiet' : 'the lamp is resting';
  footerStatus.textContent = isOn ? 'the room is quiet' : 'the lamp is resting';
}

if (lampSwitch) {
  lampSwitch.addEventListener('click', () => {
    setLampState(lampSwitch.getAttribute('aria-pressed') !== 'true');
  });
}

document.querySelectorAll('.cc-navbar__menu-panel a').forEach((link) => {
  link.addEventListener('click', () => {
    const menu = link.closest('.cc-navbar__menu');
    if (menu) menu.removeAttribute('open');
  });
});
