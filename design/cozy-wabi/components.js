const menuToggle = document.querySelector('.cc-menu-toggle');
const navigation = document.querySelector('#cc-site-navigation');

const setMenuExpanded = (expanded) => {
  menuToggle?.setAttribute('aria-expanded', String(expanded));
  navigation?.classList.toggle('is-collapsed', !expanded);
  const label = menuToggle.querySelector('.cc-menu-toggle__label');
  if (label) label.textContent = expanded ? 'close menu' : 'open menu';
};

if (menuToggle && navigation) {
  setMenuExpanded(false);
}

menuToggle?.addEventListener('click', () => {
  setMenuExpanded(menuToggle.getAttribute('aria-expanded') !== 'true');
});

document.querySelectorAll('[data-tabs]').forEach((tabGroup) => {
  const tabs = Array.from(tabGroup.querySelectorAll('[role="tab"]'));
  const panels = Array.from(tabGroup.querySelectorAll('[role="tabpanel"]'));
  if (!tabs.length || !panels.length) return;

  tabGroup.classList.add('is-enhanced');

  const activateTab = (tab, moveFocus = false) => {
    const targetId = tab.getAttribute('aria-controls');

    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute('aria-selected', String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    });

    panels.forEach((panel) => {
      panel.hidden = panel.id !== targetId;
    });

    if (moveFocus) tab.focus();
  };

  tabs.forEach((tab, index) => {
    tab.tabIndex = index === 0 ? 0 : -1;
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', (event) => {
      let nextIndex = index;

      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        nextIndex = (index + 1) % tabs.length;
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        nextIndex = (index - 1 + tabs.length) % tabs.length;
      } else if (event.key === 'Home') {
        nextIndex = 0;
      } else if (event.key === 'End') {
        nextIndex = tabs.length - 1;
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        activateTab(tab);
        return;
      } else {
        return;
      }

      event.preventDefault();
      activateTab(tabs[nextIndex], true);
    });
  });

  activateTab(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0]);
});

const range = document.querySelector('#record-warmth');
const rangeOutput = document.querySelector('#record-warmth-output');
if (range && rangeOutput) {
  const updateWarmth = () => {
    rangeOutput.value = `${range.value}%`;
    rangeOutput.textContent = `${range.value}%`;
  };
  range.addEventListener('input', updateWarmth);
  updateWarmth();
}

const setValidationMessage = (control, message) => {
  const field = control.closest('.cc-field') || control.closest('.cc-choice');
  if (!field) return;

  field.classList.add('cc-field--error');
  control.setAttribute('aria-invalid', 'true');

  let messageElement = field.querySelector('[data-validation-message]');
  if (!messageElement) {
    messageElement = document.createElement('p');
    messageElement.className = 'cc-field__error';
    messageElement.dataset.validationMessage = 'true';
    field.append(messageElement);
  }
  messageElement.textContent = message;
}

const clearValidationMessage = (control) => {
  const field = control.closest('.cc-field') || control.closest('.cc-choice');
  if (!field) return;

  field.classList.remove('cc-field--error');
  control.removeAttribute('aria-invalid');
  field.querySelector('[data-validation-message]')?.remove();
};

const controlIsValid = (control) => {
  if (control.type === 'checkbox') return control.checked;
  if (control.type === 'email') return control.value.trim() !== '' && control.validity.valid;
  return control.value.trim() !== '';
};

const demoForm = document.querySelector('[data-demo-form]');
demoForm?.querySelectorAll('[required]').forEach((control) => {
  control.addEventListener('input', () => {
    if (controlIsValid(control)) clearValidationMessage(control);
  });
  control.addEventListener('change', () => {
    if (controlIsValid(control)) clearValidationMessage(control);
  });
});

demoForm?.addEventListener('submit', (event) => {
  event.preventDefault();

  const requiredControls = Array.from(demoForm.querySelectorAll('[required]'));
  const invalidControls = requiredControls.filter((control) => !controlIsValid(control));
  const status = demoForm.querySelector('[data-form-status]');

  invalidControls.forEach((control) => {
    const message = control.type === 'email'
      ? 'Use an email like hello@example.com.'
      : control.type === 'checkbox'
        ? 'Check this before continuing.'
        : control.tagName === 'SELECT'
          ? 'Choose one small record type.'
          : 'Add a name before continuing.';
    setValidationMessage(control, message);
  });

  if (invalidControls.length) {
    status.textContent = 'A few small details need your attention.';
    status.className = 'cc-form__status is-error';
    invalidControls[0].focus();
    return;
  }

  status.textContent = 'Confirmed locally — demo record ready; nothing was sent.';
  status.className = 'cc-form__status is-success';
});

const toast = document.querySelector('[data-toast]');
const toastMessage = toast?.querySelector('[data-toast-message]');
let toastTimer;

const showToast = (message) => {
  if (!toast || !toastMessage) return;
  window.clearTimeout(toastTimer);
  toastMessage.textContent = message;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 4200);
};

document.querySelectorAll('[data-toast-trigger]').forEach((trigger) => {
  trigger.addEventListener('click', () => {
    showToast(trigger.dataset.toastTrigger || 'Toast shown — still on this page.');
  });
});

toast?.querySelector('[data-toast-dismiss]')?.addEventListener('click', () => {
  window.clearTimeout(toastTimer);
  toast.hidden = true;
});

document.querySelectorAll('[data-dialog-open]').forEach((trigger) => {
  const dialog = document.getElementById(trigger.dataset.dialogOpen);
  if (!dialog) return;

  trigger.addEventListener('click', () => {
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
      dialog.classList.add('is-open');
    }
    dialog.querySelector('button:not([data-dialog-close])')?.focus();
  });
});

document.querySelectorAll('dialog').forEach((dialog) => {
  const closeDialog = () => {
    if (typeof dialog.close === 'function' && dialog.open) {
      dialog.close('cancel');
    } else {
      dialog.removeAttribute('open');
      dialog.classList.remove('is-open');
    }
  };

  dialog.querySelectorAll('[data-dialog-close]').forEach((closeButton) => {
    closeButton.addEventListener('click', (event) => {
      event.preventDefault();
      closeDialog();
    });
  });

  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDialog();
    }
  });

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) closeDialog();
  });

  dialog.addEventListener('close', () => {
    dialog.classList.remove('is-open');
    if (dialog.returnValue === 'keep') showToast('Dialog confirmed locally — no record was created.');
  });
});
