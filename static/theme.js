(function () {
  var STORAGE_KEY = 'tsa-theme';
  var root = document.documentElement;
  var deviceQuery =
    window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
  var viewportQuery =
    window.matchMedia && window.matchMedia('(max-width: 768px)');

  function validPreference(value) {
    return value === 'light' || value === 'dark' || value === 'system';
  }

  function currentPreference() {
    var value = root.dataset.themePreference;
    return validPreference(value) ? value : 'system';
  }

  function storedPreference() {
    try {
      var stored = localStorage.getItem(STORAGE_KEY);
      return validPreference(stored) ? stored : 'system';
    } catch (_e) {
      return 'system';
    }
  }

  function resolveTheme(preference) {
    if (preference !== 'system') return preference;
    return deviceQuery && deviceQuery.matches ? 'dark' : 'light';
  }

  function syncPicker() {
    var preference = currentPreference();
    var resolved = root.dataset.theme || resolveTheme(preference);
    document.querySelectorAll('[data-theme-choice]').forEach(function (button) {
      var selected = button.dataset.themeChoice === preference;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-checked', selected ? 'true' : 'false');
    });
    document.querySelectorAll('[data-theme-current-icon]').forEach(function (icon) {
      icon.hidden = icon.dataset.themeCurrentIcon !== preference;
    });
    document.querySelectorAll('[data-theme-trigger]').forEach(function (button) {
      button.setAttribute(
        'aria-label',
        preference === 'system'
          ? 'Theme: match device'
          : 'Theme: ' + resolved + ' mode'
      );
      button.title =
        preference === 'system'
          ? 'Theme: Match device'
          : 'Theme: ' + resolved.charAt(0).toUpperCase() + resolved.slice(1);
    });
  }

  function applyTheme(preference, persist) {
    if (!validPreference(preference)) preference = 'system';
    var resolved = resolveTheme(preference);
    root.dataset.themePreference = preference;
    root.dataset.theme = resolved;
    root.style.colorScheme = resolved;
    if (persist !== false) {
      try {
        localStorage.setItem(STORAGE_KEY, preference);
      } catch (_e) {}
    }
    syncPicker();
    window.dispatchEvent(
      new CustomEvent('tsa-theme-change', {
        detail: { preference: preference, resolved: resolved },
      })
    );
  }

  function closePicker(picker) {
    if (!picker) return;
    var trigger = picker.querySelector('[data-theme-trigger]');
    var menu = picker.querySelector('[data-theme-menu]');
    if (!trigger || !menu) return;
    picker.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    clearTimeout(picker._themeCloseTimer);
    if (menu.hidden) return;
    picker._themeCloseTimer = setTimeout(function () {
      if (!picker.classList.contains('is-open')) menu.hidden = true;
    }, 240);
  }

  function openPicker(picker, trigger, menu) {
    clearTimeout(picker._themeCloseTimer);
    menu.hidden = false;
    void picker.offsetHeight;
    picker.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    var selected = menu.querySelector('[aria-checked="true"]');
    if (selected) selected.focus();
  }

  function initPicker(picker) {
    var trigger = picker.querySelector('[data-theme-trigger]');
    var menu = picker.querySelector('[data-theme-menu]');
    if (!trigger || !menu) return;

    trigger.addEventListener('click', function () {
      var willOpen = !picker.classList.contains('is-open');
      document.querySelectorAll('[data-theme-picker]').forEach(function (other) {
        if (other !== picker) closePicker(other);
      });
      if (willOpen) openPicker(picker, trigger, menu);
      else closePicker(picker);
    });

    menu.querySelectorAll('[data-theme-choice]').forEach(function (button) {
      button.addEventListener('click', function () {
        applyTheme(button.dataset.themeChoice, true);
        closePicker(picker);
        trigger.focus();
      });
    });

    picker.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closePicker(picker);
        trigger.focus();
        return;
      }
      if (
        menu.hidden ||
        (event.key !== 'ArrowDown' && event.key !== 'ArrowUp')
      ) {
        return;
      }
      var choices = Array.prototype.slice.call(
        menu.querySelectorAll('[data-theme-choice]')
      );
      var current = choices.indexOf(document.activeElement);
      var direction = event.key === 'ArrowDown' ? 1 : -1;
      if (current < 0) current = direction > 0 ? -1 : 0;
      var next = (current + direction + choices.length) % choices.length;
      event.preventDefault();
      choices[next].focus();
    });
  }

  document.querySelectorAll('[data-theme-picker]').forEach(initPicker);
  document.addEventListener('click', function (event) {
    document.querySelectorAll('[data-theme-picker]').forEach(function (picker) {
      if (!picker.contains(event.target)) closePicker(picker);
    });
  });
  var searchInput = document.getElementById('airport-search');
  if (searchInput) {
    searchInput.addEventListener('focus', function () {
      document.querySelectorAll('[data-theme-picker]').forEach(closePicker);
    });
  }

  if (deviceQuery) {
    var onDeviceThemeChange = function () {
      if (currentPreference() === 'system') applyTheme('system', false);
    };
    if (deviceQuery.addEventListener) {
      deviceQuery.addEventListener('change', onDeviceThemeChange);
    } else if (deviceQuery.addListener) {
      deviceQuery.addListener(onDeviceThemeChange);
    }
  }
  if (viewportQuery) {
    var onThemeViewportChange = function () {
      applyTheme(viewportQuery.matches ? 'system' : storedPreference(), false);
      document.querySelectorAll('[data-theme-picker]').forEach(closePicker);
    };
    if (viewportQuery.addEventListener) {
      viewportQuery.addEventListener('change', onThemeViewportChange);
    } else if (viewportQuery.addListener) {
      viewportQuery.addListener(onThemeViewportChange);
    }
  }

  syncPicker();
  window.tsaTheme = {
    apply: function (preference) {
      applyTheme(preference, true);
    },
    preference: currentPreference,
  };
})();
