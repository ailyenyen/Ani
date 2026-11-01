/* Ani: small progressive enhancements. Every page works without this file. */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  var reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function store(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch (e) { /* private mode: the choice just isn't remembered */ }
  }
  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  // --- Light / dark mode --------------------------------------------------

  var toggles = document.querySelectorAll("[data-theme-toggle]");

  function syncThemeButtons() {
    var dark = root.getAttribute("data-theme") === "dark";
    toggles.forEach(function (button) {
      button.setAttribute("aria-pressed", dark ? "true" : "false");
      var label = button.querySelector("[data-theme-label]");
      if (label) label.textContent = dark ? "Switch to light mode" : "Switch to dark mode";
      button.title = dark ? "Switch to light mode" : "Switch to dark mode";
    });
  }

  function applyTheme(theme, animate) {
    if (animate && !reduceMotion) {
      root.classList.add("theme-switching");
      window.setTimeout(function () { root.classList.remove("theme-switching"); }, 400);
    }
    root.setAttribute("data-theme", theme);
    syncThemeButtons();
    document.dispatchEvent(new CustomEvent("ani:themechange", { detail: { theme: theme } }));
  }

  toggles.forEach(function (button) {
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      store("ani-theme", next);
      applyTheme(next, true);
    });
  });
  syncThemeButtons();

  // Follow the device setting until the person picks a theme themselves.
  if (window.matchMedia) {
    var scheme = matchMedia("(prefers-color-scheme: dark)");
    var onScheme = function (event) {
      if (!read("ani-theme")) applyTheme(event.matches ? "dark" : "light", true);
    };
    if (scheme.addEventListener) scheme.addEventListener("change", onScheme);
  }

  // --- Side menu: collapsible rail on desktop, drawer on smaller screens ---

  var sidebar = document.getElementById("sidebar");
  if (sidebar) {
    var wide = window.matchMedia("(min-width: 960px)");
    var overlay = document.querySelector(".drawer-overlay");
    var openButtons = document.querySelectorAll("[data-drawer-open]");
    var toggleButton = sidebar.querySelector("[data-sidebar-toggle]");
    var toggleLabel = sidebar.querySelector("[data-sidebar-label]");
    var lastFocus = null;

    var syncSidebarButton = function () {
      if (!toggleButton) return;
      if (wide.matches) {
        var collapsed = root.classList.contains("sidebar-collapsed");
        toggleButton.setAttribute("aria-expanded", collapsed ? "false" : "true");
        if (toggleLabel) toggleLabel.textContent = collapsed ? "Expand menu" : "Collapse menu";
        toggleButton.title = collapsed ? "Expand menu" : "Collapse menu";
      } else {
        toggleButton.setAttribute("aria-expanded", "true");
        if (toggleLabel) toggleLabel.textContent = "Close menu";
        toggleButton.title = "Close menu";
      }
    };

    var openDrawer = function () {
      lastFocus = document.activeElement;
      if (overlay) overlay.hidden = false;
      root.classList.add("drawer-open");
      openButtons.forEach(function (b) { b.setAttribute("aria-expanded", "true"); });
      window.setTimeout(function () {
        var first = sidebar.querySelector("a, button");
        if (first) first.focus();
      }, 50);
    };

    var closeDrawer = function () {
      if (!root.classList.contains("drawer-open")) return;
      root.classList.remove("drawer-open");
      openButtons.forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
      window.setTimeout(function () { if (overlay) overlay.hidden = true; }, 320);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    };

    openButtons.forEach(function (b) { b.addEventListener("click", openDrawer); });
    if (overlay) overlay.addEventListener("click", closeDrawer);

    if (toggleButton) {
      toggleButton.addEventListener("click", function () {
        if (wide.matches) {
          var collapsed = root.classList.toggle("sidebar-collapsed");
          store("ani-sidebar", collapsed ? "collapsed" : null);
          syncSidebarButton();
          // Charts need to re-measure after the width animation.
          window.setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 320);
        } else {
          closeDrawer();
        }
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeDrawer();
      // Keep keyboard focus inside the open drawer.
      if (event.key === "Tab" && root.classList.contains("drawer-open")) {
        var items = sidebar.querySelectorAll("a, button");
        if (!items.length) return;
        var first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    });

    var onWidth = function () {
      if (wide.matches) closeDrawer();
      syncSidebarButton();
    };
    if (wide.addEventListener) wide.addEventListener("change", onWidth);
    syncSidebarButton();
  }

  // --- Landing page: header shadow, reveal on scroll, counting numbers ---

  var header = document.querySelector("[data-lp-header]");
  if (header) {
    var onScroll = function () { header.classList.toggle("is-scrolled", window.scrollY > 8); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  var revealItems = document.querySelectorAll(".reveal");
  var countUp = function (el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (!target || reduceMotion) return;
    var start = null, duration = 900;
    var step = function (time) {
      if (start === null) start = time;
      var t = Math.min((time - start) / duration, 1);
      el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) window.requestAnimationFrame(step);
    };
    el.textContent = "0";
    window.requestAnimationFrame(step);
  };

  if (revealItems.length) {
    if ("IntersectionObserver" in window && !reduceMotion) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          entry.target.querySelectorAll("[data-count]").forEach(countUp);
          observer.unobserve(entry.target);
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
      revealItems.forEach(function (el) { observer.observe(el); });
    } else {
      revealItems.forEach(function (el) { el.classList.add("is-visible"); });
    }
  }

  // --- Forms and tables ---------------------------------------------------

  // Filters marked data-autosubmit apply as soon as a choice is made.
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (select.form) select.form.submit();
    });
  });

  // Alert form: show the current price of the chosen crop under the price box.
  var hint = document.querySelector("[data-price-hint]");
  if (hint) {
    var radios = document.querySelectorAll('input[name="crop"]');
    var update = function () {
      var checked = document.querySelector('input[name="crop"]:checked');
      if (!checked) return;
      var price = checked.getAttribute("data-price");
      var name = checked.getAttribute("data-name");
      hint.textContent = price
        ? "Right now, " + name + " is ₱" + Number(price).toFixed(2) + " per kilo."
        : "We don't have a recent price for " + name + " yet.";
    };
    radios.forEach(function (radio) { radio.addEventListener("change", update); });
    update();
  }

  // Confirm before deleting.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });

  // Table rows open the crop page when tapped anywhere on the row.
  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button")) return;
      window.location.href = row.getAttribute("data-href");
    });
  });
})();
