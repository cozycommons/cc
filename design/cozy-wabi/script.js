const toggle = document.querySelector('.lamp-toggle');
const menuToggle = document.querySelector('.site-menu-toggle');
const siteNavigation = document.querySelector('#site-navigation');

toggle?.addEventListener('click', () => {
  const awake = document.body.classList.toggle('is-awake');
  toggle.setAttribute('aria-pressed', String(awake));
});

const setMenuExpanded = (expanded) => {
  menuToggle?.setAttribute('aria-expanded', String(expanded));
  siteNavigation?.classList.toggle('is-collapsed', !expanded);
  const label = menuToggle.querySelector('.site-menu-toggle__label');
  if (label) label.textContent = expanded ? 'close menu' : 'open menu';
};

if (menuToggle && siteNavigation) {
  setMenuExpanded(false);
}

menuToggle?.addEventListener('click', () => {
  setMenuExpanded(menuToggle.getAttribute('aria-expanded') !== 'true');
});
