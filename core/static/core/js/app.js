/* Ani: small progressive enhancements. Every page works without this file. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

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
})();
