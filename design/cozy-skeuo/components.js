(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  document.querySelectorAll('.cc-navbar__menu-panel a').forEach((link) => {
    link.addEventListener('click', () => {
      const menu = link.closest('.cc-navbar__menu');
      if (menu) menu.removeAttribute('open');
    });
  });

  document.querySelectorAll('[data-range-output]').forEach((range) => {
    const output = document.getElementById(range.dataset.rangeOutput);
    if (!output) return;

    const updateRangeOutput = () => {
      output.value = range.value;
      output.textContent = `${range.value}%`;
    };

    range.addEventListener('input', updateRangeOutput);
    updateRangeOutput();
  });

  document.querySelectorAll('[data-demo-switch]').forEach((switchButton) => {
    const label = switchButton.querySelector('[data-switch-label]');

    const updateSwitch = (isOn) => {
      switchButton.setAttribute('aria-pressed', String(isOn));
      if (label) label.textContent = isOn ? 'on' : 'off';
    };

    switchButton.addEventListener('click', () => {
      updateSwitch(switchButton.getAttribute('aria-pressed') !== 'true');
    });
  });

  const segments = [...document.querySelectorAll('[data-segment]')];
  const segmentOutput = document.querySelector('[data-segment-output]');

  const selectSegment = (selectedSegment) => {
    segments.forEach((segment) => {
      segment.setAttribute('aria-pressed', String(segment === selectedSegment));
    });

    if (segmentOutput && selectedSegment) {
      segmentOutput.textContent = `density: ${selectedSegment.dataset.segmentValue}`;
    }
  };

  segments.forEach((segment) => {
    segment.addEventListener('click', () => selectSegment(segment));
  });

  document.querySelectorAll('[data-tabs]').forEach((tabSet) => {
    const tabs = [...tabSet.querySelectorAll('[role="tab"]')];
    const panels = [...tabSet.querySelectorAll('[data-tab-panel]')];
    const tabList = tabSet.querySelector('[role="tablist"]');

    const activateTab = (selectedTab, shouldFocus = false) => {
      tabs.forEach((tab) => {
        const isSelected = tab === selectedTab;
        const panel = document.getElementById(tab.getAttribute('aria-controls'));
        tab.setAttribute('aria-selected', String(isSelected));
        tab.tabIndex = isSelected ? 0 : -1;
        if (panel) {
          panel.hidden = !isSelected;
          panel.setAttribute('aria-hidden', String(!isSelected));
        }
      });

      if (shouldFocus) selectedTab.focus();
    };

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => activateTab(tab));
    });

    if (tabList) {
      tabList.addEventListener('keydown', (event) => {
        const currentIndex = tabs.indexOf(document.activeElement);
        if (currentIndex === -1) return;

        let nextIndex = currentIndex;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % tabs.length;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = tabs.length - 1;
        if (nextIndex === currentIndex) return;

        event.preventDefault();
        activateTab(tabs[nextIndex], true);
      });
    }

    const selectedTab = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0];
    if (selectedTab) activateTab(selectedTab);
    if (!panels.length) return;
  });

  const searchStatusMessages = [...document.querySelectorAll('[data-search-status]')];
  document.querySelectorAll('[data-component-search]').forEach((searchInput) => {
    searchInput.addEventListener('input', () => {
      const query = searchInput.value.trim();
      const message = query
        ? `Local search ready for “${query}”. Matching is a demo response.`
        : 'Try “button”, “card”, or “field”.';
      searchStatusMessages.forEach((status) => {
        status.textContent = message;
      });
    });
  });

  const demoForm = document.querySelector('[data-demo-form]');
  if (demoForm) {
    const feedback = demoForm.querySelector('[data-form-feedback]');
    const fields = [...demoForm.querySelectorAll('.cc-field')];

    const markInvalidFields = () => {
      fields.forEach((field) => {
        const controls = [...field.querySelectorAll('input, textarea, select')];
        const hasInvalidControl = controls.some((control) => control.willValidate && !control.checkValidity());
        field.classList.toggle('is-error', hasInvalidControl);
      });
    };

    demoForm.addEventListener('input', (event) => {
      const field = event.target.closest('.cc-field');
      if (field) {
        const controls = [...field.querySelectorAll('input, textarea, select')];
        field.classList.toggle('is-error', controls.some((control) => control.willValidate && !control.checkValidity()));
      }
      if (feedback && demoForm.classList.contains('has-errors')) {
        feedback.textContent = '';
        feedback.classList.remove('is-error');
      }
    });

    demoForm.addEventListener('submit', (event) => {
      event.preventDefault();
      markInvalidFields();

      if (!demoForm.checkValidity()) {
        demoForm.classList.add('has-errors');
        if (feedback) {
          feedback.textContent = 'A few fields need attention before the card can be confirmed.';
          feedback.classList.add('is-error');
        }
        demoForm.reportValidity();
        return;
      }

      demoForm.classList.remove('has-errors');
      fields.forEach((field) => field.classList.remove('is-error'));
      if (feedback) {
        const name = demoForm.querySelector('[name="name"]')?.value.trim();
        feedback.textContent = `Confirmed locally${name ? ` for ${name}` : ''}. Nothing was sent.`;
        feedback.classList.remove('is-error');
      }
    });
  }

  const dialog = document.querySelector('[data-dialog]');
  const openDialogButton = document.querySelector('[data-dialog-open]');
  const dialogStatus = document.querySelector('[data-dialog-status]');

  if (dialog && openDialogButton) {
    const supportsModal = typeof dialog.showModal === 'function';
    let closedWithEscape = false;

    openDialogButton.addEventListener('click', () => {
      closedWithEscape = false;
      if (supportsModal) {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
    });

    dialog.addEventListener('cancel', () => {
      closedWithEscape = true;
    });

    dialog.addEventListener('close', () => {
      if (!dialogStatus) return;
      const result = dialog.returnValue;
      dialogStatus.textContent = closedWithEscape
        ? 'Dialog closed with Escape.'
        : result === 'confirm' ? 'Sample accepted locally.' : 'Dialog closed locally.';
    });

    if (!supportsModal) {
      dialog.querySelector('form')?.addEventListener('submit', (event) => {
        event.preventDefault();
        dialog.removeAttribute('open');
        if (dialogStatus) dialogStatus.textContent = 'Dialog closed locally.';
      });

      dialog.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          dialog.removeAttribute('open');
          if (dialogStatus) dialogStatus.textContent = 'Dialog closed with Escape.';
        }
      });
    }
  }

  const toast = document.querySelector('[data-toast]');
  const toastTrigger = document.querySelector('[data-toast-trigger]');
  const toastDismiss = document.querySelector('[data-toast-dismiss]');
  let toastTimer;

  if (toast && toastTrigger) {
    const hideToast = () => {
      window.clearTimeout(toastTimer);
      toast.hidden = true;
    };

    toastTrigger.addEventListener('click', () => {
      window.clearTimeout(toastTimer);
      toast.hidden = false;
      if (!reduceMotion) toastTimer = window.setTimeout(hideToast, 4200);
    });

    toastDismiss?.addEventListener('click', hideToast);
  }
})();
