(() => {
  const header = document.querySelector('[data-site-header]');
  const menuButton = document.querySelector('[data-menu-button]');

  if (header && menuButton) {
    header.dataset.menuReady = 'true';
    const menuLabel = menuButton.querySelector('.sr-only');
    const setMenu = (open) => {
      header.dataset.menuOpen = String(open);
      menuButton.setAttribute('aria-expanded', String(open));
      if (menuLabel) menuLabel.textContent = open ? 'Close navigation' : 'Open navigation';
    };
    setMenu(false);
    menuButton.addEventListener('click', () => setMenu(menuButton.getAttribute('aria-expanded') !== 'true'));
    document.querySelectorAll('#component-nav a').forEach((link) => link.addEventListener('click', () => setMenu(false)));
  }

  const bindRange = (rangeId, outputId) => {
    const range = document.getElementById(rangeId);
    const output = document.getElementById(outputId);
    if (!range || !output) return;
    const update = () => {
      output.value = `${range.value}%`;
      output.textContent = `${range.value}%`;
    };
    range.addEventListener('input', update);
    update();
  };

  bindRange('hero-confidence', 'hero-confidence-output');
  bindRange('demo-confidence', 'demo-confidence-output');

  const enhanceTabs = (container, tabs, panels, targetForTab) => {
    if (!container || tabs.length === 0) return;
    container.classList.add('is-enhanced');

    const activate = (tab, focus = false) => {
      const targetId = targetForTab(tab);
      tabs.forEach((candidate) => {
        const selected = candidate === tab;
        candidate.setAttribute('aria-selected', String(selected));
        candidate.classList.toggle('is-selected', selected);
        candidate.tabIndex = selected ? 0 : -1;
      });
      panels.forEach((panel) => { panel.hidden = panel.id !== targetId; });
      if (focus) tab.focus();
    };

    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => activate(tab));
      tab.addEventListener('keydown', (event) => {
        let next = index;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = tabs.length - 1;
        else if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          activate(tab);
          return;
        } else return;
        event.preventDefault();
        activate(tabs[next], true);
      });
    });

    activate(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0]);
  };

  document.querySelectorAll('[data-segmented]').forEach((container) => {
    enhanceTabs(
      container,
      [...container.querySelectorAll('[role="tab"]')],
      [...container.parentElement.querySelectorAll('[data-segment-panel]')],
      (tab) => tab.dataset.panelTarget,
    );
  });

  document.querySelectorAll('[data-tabset]').forEach((container) => {
    enhanceTabs(
      container,
      [...container.querySelectorAll('[role="tab"]')],
      [...container.querySelectorAll('[role="tabpanel"]')],
      (tab) => tab.getAttribute('aria-controls'),
    );
  });

  const form = document.querySelector('[data-local-form]');
  const formStatus = document.getElementById('demo-form-status');
  const fieldErrorId = (control) => {
    if (control.name === 'result') return null;
    if (control.name === 'consent') return 'demo-consent-error';
    return `${control.id}-error`;
  };

  const updateField = (control) => {
    const valid = control.checkValidity();
    const errorId = fieldErrorId(control);
    const error = errorId ? document.getElementById(errorId) : null;
    control.classList.toggle('is-error', !valid);
    control.setAttribute('aria-invalid', String(!valid));
    if (error) error.hidden = valid;
    return valid;
  };

  if (form) {
    const required = [...form.querySelectorAll('[required]')];
    required.forEach((control) => {
      control.addEventListener('input', () => updateField(control));
      control.addEventListener('change', () => updateField(control));
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const invalid = required.filter((control) => !updateField(control));
      if (invalid.length) {
        if (formStatus) {
          formStatus.textContent = 'A few demo fields need attention before continuing.';
          formStatus.classList.add('is-error');
        }
        invalid[0].focus();
        return;
      }
      if (formStatus) {
        formStatus.textContent = 'Confirmed locally — the demo record was not sent or saved.';
        formStatus.classList.remove('is-error');
      }
    });

    form.addEventListener('reset', () => window.setTimeout(() => {
      required.forEach((control) => {
        control.classList.remove('is-error');
        control.removeAttribute('aria-invalid');
        const errorId = fieldErrorId(control);
        if (errorId) document.getElementById(errorId)?.setAttribute('hidden', '');
      });
      bindRange('demo-confidence', 'demo-confidence-output');
      if (formStatus) {
        formStatus.textContent = 'Nothing leaves this page. Required fields are marked for the demo.';
        formStatus.classList.remove('is-error');
      }
    }, 0));
  }

  const toast = document.getElementById('demo-toast');
  const toastCopy = toast?.querySelector('[data-toast-copy]');
  let toastTimer;
  const hideToast = () => {
    window.clearTimeout(toastTimer);
    if (toast) toast.hidden = true;
  };
  document.querySelectorAll('[data-toast-trigger]').forEach((trigger) => trigger.addEventListener('click', () => {
    if (!toast) return;
    window.clearTimeout(toastTimer);
    if (toastCopy) toastCopy.textContent = trigger.dataset.toastTrigger || 'A small local toast appeared.';
    toast.hidden = false;
    toastTimer = window.setTimeout(hideToast, 4200);
  }));
  toast?.querySelector('[data-toast-dismiss]')?.addEventListener('click', hideToast);

  document.querySelectorAll('[data-dialog-open]').forEach((trigger) => {
    const dialog = document.getElementById(trigger.dataset.dialogOpen);
    trigger.addEventListener('click', () => dialog?.showModal?.());
  });
})();
