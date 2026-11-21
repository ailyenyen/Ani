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
  document.querySelectorAll("select[data-autosubmit], input[type=checkbox][data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (select.form) select.form.submit();
    });
  });

  var filters = document.querySelector("[data-comparison-filters]");
  if (filters) {
    var regionOptions = filters.querySelectorAll('input[name="region"]');
    var regionCount = filters.querySelector("[data-region-count]");
    var clearRegions = filters.querySelector("[data-clear-regions]");
    var windowSummary = filters.querySelector("[data-window-summary]");
    var dateLabel = new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric"});
    var updateRegions = function () {
      var selected = filters.querySelectorAll('input[name="region"]:checked').length;
      regionCount.textContent = selected ? selected + " selected" : "All regions";
      clearRegions.hidden = selected === 0;
    };
    var updateWindow = function () {
      var windowOption = filters.querySelector('input[name="days"]:checked');
      var endDate = new Date(filters.elements.as_of.value + "T00:00:00");
      var suffix = Number.isNaN(endDate.getTime()) ? "" : " through " + dateLabel.format(endDate);
      windowSummary.textContent = filters.elements.report_date.value ? "Exact date selected"
        : (windowOption ? windowOption.closest("label").textContent.trim() + suffix : "Choose a window");
    };
    regionOptions.forEach(function (option) { option.addEventListener("change", updateRegions); });
    clearRegions.addEventListener("click", function () {
      regionOptions.forEach(function (option) { option.checked = false; });
      updateRegions();
      regionCount.closest("summary").focus();
    });
    filters.querySelectorAll('input[name="days"], input[name="as_of"], select[name="report_date"]').forEach(function (option) {
      option.addEventListener("change", updateWindow);
    });
    updateRegions();
    updateWindow();
  }

  var priceText = function (name, price, label) {
    if (!price) return "We don't have a recent price for " + name + " yet.";
    var peso = "₱" + Number(price).toFixed(2) + " per kilo";
    return label ? label + ": " + peso + "." : "Right now, " + name + " is " + peso + ".";
  };

  // Searchable crop picker: turns <select data-combobox> into a type-to-filter list.
  document.querySelectorAll("select[data-combobox]").forEach(function (select, n) {
    var wrap = document.createElement("div");
    wrap.className = "combo";
    var listId = "combo-list-" + n;
    wrap.innerHTML = '<div class="combo-input-wrap">' + (select.getAttribute("data-icon") || "") +
      '<input class="combo-input" type="text" role="combobox" autocomplete="off" aria-autocomplete="list" aria-expanded="false" aria-controls="' + listId + '"></div>' +
      '<ul class="combo-list" role="listbox" id="' + listId + '" hidden></ul>';
    var input = wrap.querySelector("input"), list = wrap.querySelector("ul");
    input.placeholder = select.getAttribute("data-placeholder") || "Search";
    if (select.id) { input.id = select.id; select.removeAttribute("id"); }
    select.hidden = true;
    select.parentNode.insertBefore(wrap, select);
    var options = Array.prototype.filter.call(select.options, function (o) { return o.value; });
    var active = -1, shown = [];
    var render = function () {
      var terms = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      shown = options.filter(function (o) {
        var text = (o.textContent + " " + (o.getAttribute("data-search") || "")).toLowerCase();
        return terms.every(function (t) { return text.indexOf(t) !== -1; });
      }).slice(0, 60);
      list.innerHTML = "";
      if (!shown.length) {
        list.innerHTML = '<li class="combo-empty">No crop matches “' + input.value.replace(/[<>&"]/g, "") + '”</li>';
      }
      shown.forEach(function (o, i) {
        var li = document.createElement("li");
        li.className = "combo-option" + (i === active ? " is-active" : "");
        li.id = listId + "-" + i;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", o.selected ? "true" : "false");
        var name = document.createElement("span");
        name.textContent = o.textContent;
        li.appendChild(name);
        if (o.getAttribute("data-price")) {
          var price = document.createElement("small");
          price.textContent = "₱" + Number(o.getAttribute("data-price")).toFixed(2) + "/kg";
          li.appendChild(price);
        }
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(o); });
        list.appendChild(li);
      });
      input.setAttribute("aria-activedescendant", active >= 0 ? listId + "-" + active : "");
    };
    var open = function () { active = -1; render(); list.hidden = false; input.setAttribute("aria-expanded", "true"); };
    var close = function () { list.hidden = true; input.setAttribute("aria-expanded", "false"); };
    var choose = function (o) {
      select.value = o.value;
      input.value = o.textContent;
      close();
      select.dispatchEvent(new Event("change"));
    };
    var chosen = options.filter(function (o) { return o.selected; })[0];
    if (chosen) input.value = chosen.textContent;
    input.addEventListener("focus", function () { input.select(); open(); });
    input.addEventListener("input", open);
    input.addEventListener("blur", function () {
      close();
      var current = options.filter(function (o) { return o.value === select.value; })[0];
      input.value = current ? current.textContent : "";
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (list.hidden) open();
        active = Math.max(0, Math.min(shown.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
        render();
        var el = document.getElementById(listId + "-" + active);
        if (el) el.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && !list.hidden) {
        e.preventDefault();
        if (shown[active >= 0 ? active : 0]) choose(shown[active >= 0 ? active : 0]);
      } else if (e.key === "Escape") {
        close();
      }
    });
  });

  // Alert page: show the current price of the chosen crop under the price box.
  var hint = document.querySelector("[data-price-hint]");
  var cropSelect = document.querySelector("select[name=crop]");
  if (hint && cropSelect) {
    var update = function () {
      var o = cropSelect.options[cropSelect.selectedIndex];
      if (!o || !o.value) return;
      hint.textContent = priceText(o.textContent, o.getAttribute("data-price"));
    };
    cropSelect.addEventListener("change", update);
    update();
  }

  // --- Dialogs -------------------------------------------------------------
  var openDialog = function (dialog) {
    if (!dialog || typeof dialog.showModal !== "function") return false;
    document.querySelectorAll("details.kebab[open]").forEach(function (d) { d.open = false; });
    dialog.showModal();
    return true;
  };
  document.querySelectorAll("dialog.ani-dialog").forEach(function (dialog) {
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
      button.addEventListener("click", function () { dialog.close(); });
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close(); // a tap on the backdrop
    });
  });
  document.querySelectorAll("[data-dialog-open]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (openDialog(document.getElementById(link.getAttribute("data-dialog-open")))) event.preventDefault();
    });
  });
  if (location.hash === "#add") openDialog(document.getElementById("add-dialog"));

  // Close "more" menus when tapping elsewhere.
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.kebab[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });

  // --- New price alert dialog ----------------------------------------------
  var alertDialog = document.getElementById("alert-dialog");
  if (alertDialog && typeof alertDialog.showModal === "function") {
    var form = alertDialog.querySelector("form");
    var target = form.elements.target_price;
    var chips = form.querySelector("[data-alert-chips]");
    var status = form.querySelector("[data-alert-status]");
    var submit = form.querySelector("[data-alert-submit]");
    var search = form.querySelector("[data-alert-search]");
    var fixedCrop = form.querySelector("[data-alert-crop]");
    var choices = Array.prototype.slice.call(form.querySelectorAll(".alert-choice:not(.is-fixed)"));
    var fixed = {};
    var money = function (n) { return "₱" + n.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };

    var chosen = function () {
      if (fixedCrop) return fixedCrop.value ? fixed : null;
      var radio = form.querySelector('input[name="crop"]:checked');
      return radio ? { name: radio.getAttribute("data-name"), low: radio.getAttribute("data-low"), high: radio.getAttribute("data-high") } : null;
    };
    var refresh = function () {
      var crop = chosen();
      var above = form.elements.condition.value !== "below";
      chips.innerHTML = "";
      if (crop && crop.high) {
        // Quick targets from today's price: the top of the range when watching for a rise, the bottom for a drop.
        var base = Number(above ? crop.high : crop.low);
        [5, 10].forEach(function (pct) {
          var value = Math.round(base * (above ? 1 + pct / 100 : 1 - pct / 100) * 100) / 100;
          var chip = document.createElement("button");
          chip.type = "button";
          chip.textContent = money(value) + " (" + (above ? "+" : "−") + pct + "%)";
          chip.addEventListener("click", function () { target.value = value.toFixed(2); refresh(); });
          chips.appendChild(chip);
        });
      }
      var price = Number(target.value);
      var valid = crop && target.value && target.checkValidity() && price > 0;
      submit.disabled = !valid;
      if (!crop && !target.value) status.textContent = "Choose a crop and a target price to create the alert.";
      else if (!crop) status.textContent = "Choose a crop to watch.";
      else if (!valid) status.textContent = "Type a target price, like 40 or 22.50.";
      else status.textContent = "We’ll tell you when " + crop.name + " " + (above ? "rises above " : "drops below ") + money(price) + "/kg.";
    };
    form.addEventListener("change", refresh);
    target.addEventListener("input", refresh);

    if (search) {
      var none = form.querySelector("[data-alert-none]");
      search.addEventListener("input", function () {
        var terms = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
        var shown = 0;
        choices.forEach(function (choice) {
          var text = choice.getAttribute("data-search");
          var match = terms.every(function (t) { return text.indexOf(t) !== -1; }) || choice.querySelector("input").checked;
          choice.hidden = !match;
          if (match) shown++;
        });
        none.hidden = shown > 0;
      });
    }

    document.querySelectorAll("[data-alert-open]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        var slug = button.getAttribute("data-crop");
        if (fixedCrop && !slug) return; // no crop list on this page: use the full alert page
        event.preventDefault();
        form.reset();
        if (search) { search.value = ""; search.dispatchEvent(new Event("input")); }
        if (fixedCrop) {
          fixedCrop.value = slug;
          fixed = { name: button.getAttribute("data-name"), low: button.getAttribute("data-low") || button.getAttribute("data-price"),
                    high: button.getAttribute("data-high") || button.getAttribute("data-price") };
          var price = button.getAttribute("data-price") || button.getAttribute("data-high");
          form.querySelector("[data-alert-name]").textContent = fixed.name;
          form.querySelector("[data-alert-note]").textContent = price ? (button.getAttribute("data-price-label") || "Now") : "No recent price";
          form.querySelector("[data-alert-price]").textContent = price ? money(Number(price)) : "No price";
        } else if (slug) {
          var radio = form.querySelector('input[name="crop"][value="' + slug.replace(/"/g, "") + '"]');
          if (radio) radio.checked = true;
        }
        refresh();
        openDialog(alertDialog);
        var picked = form.querySelector('input[name="crop"]:checked');
        if (picked) picked.closest(".alert-choice").scrollIntoView({ block: "nearest" });
        (slug ? target : (search || target)).focus();
      });
    });
  }

  // --- Add crops dialog ------------------------------------------------------
  var addForm = document.querySelector("[data-add-form]");
  if (addForm) {
    var addSearch = addForm.querySelector("[data-add-search]");
    var groups = Array.prototype.slice.call(addForm.querySelectorAll(".add-group"));
    var category = "";
    var filterGroups = function () {
      var terms = addSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      groups.forEach(function (group) {
        var text = group.getAttribute("data-search");
        var match = (!category || group.getAttribute("data-category") === category) &&
          terms.every(function (t) { return text.indexOf(t) !== -1; });
        group.hidden = !match;
        if (match) shown++;
      });
      addForm.querySelector("[data-add-none]").hidden = shown > 0;
    };
    addSearch.addEventListener("input", filterGroups);
    addForm.querySelectorAll("[data-add-category]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        category = chip.getAttribute("data-add-category");
        addForm.querySelectorAll("[data-add-category]").forEach(function (c) { c.setAttribute("aria-pressed", String(c === chip)); });
        filterGroups();
      });
    });
    var count = addForm.querySelector("[data-add-count]"), addSubmit = addForm.querySelector("[data-add-submit]");
    addForm.addEventListener("change", function () {
      var n = addForm.querySelectorAll('input[name="crop"]:checked').length;
      count.textContent = n ? n + " variet" + (n === 1 ? "y" : "ies") + " selected" : "No variety selected";
      addSubmit.disabled = n === 0;
      addSubmit.textContent = n ? "Add " + n + " to My Crops" : "Add to My Crops";
    });
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
