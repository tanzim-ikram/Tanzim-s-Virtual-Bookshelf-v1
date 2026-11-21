/* Tanzim's Virtual Bookshelf: small vanilla-JS helpers. No libraries. */
(function () {
  "use strict";

  function $(selector, root) { return (root || document).querySelector(selector); }
  function $$(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  /* ---------- Phone menu ---------- */
  var menuBtn = $(".menu-btn");
  var nav = $("#site-nav");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* ---------- Flash messages + confirm-before-submit ---------- */
  document.addEventListener("click", function (event) {
    var dismiss = event.target.closest("[data-dismiss]");
    if (dismiss) { dismiss.parentElement.remove(); }
  });

  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) { event.preventDefault(); }
  });

  /* ---------- Book cards: tap to flip on touch devices ----------
     On devices with a mouse the card flips on hover (pure CSS). */
  function closeCards(except) {
    $$(".book.is-flipped").forEach(function (card) {
      if (card !== except) { card.classList.remove("is-flipped"); }
    });
  }

  document.addEventListener("click", function (event) {
    var canHover = window.matchMedia("(hover: hover)").matches;
    var card = event.target.closest(".book");

    if (!card) { closeCards(null); return; }
    if (canHover) { return; }

    if (event.target.closest(".flip-toggle")) {
      closeCards(card);
      card.classList.toggle("is-flipped");
    } else if (event.target.closest(".flip-close")) {
      card.classList.remove("is-flipped");
    } else if (event.target.closest(".back") && !event.target.closest("a, button, form")) {
      card.classList.remove("is-flipped");
    }
  });

  /* ---------- Home page filters ---------- */
  var chips = $$(".chip[data-filter]");
  if (chips.length) {
    var cards = $$(".grid .book");
    var countEl = $("#count");
    var emptyEl = $("#empty");

    var matches = function (card, filter) {
      if (filter === "all") { return true; }
      if (filter === "read") { return card.dataset.read === "yes"; }
      if (filter === "unread") { return card.dataset.read === "no"; }
      return card.dataset.lang === filter;
    };

    var apply = function (filter) {
      var shown = 0;
      cards.forEach(function (card) {
        var show = matches(card, filter);
        card.hidden = !show;
        if (show) { shown += 1; }
      });
      if (countEl) { countEl.textContent = "Showing " + shown + (shown === 1 ? " book" : " books"); }
      if (emptyEl) { emptyEl.hidden = shown !== 0; }
    };

    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chips.forEach(function (c) { c.setAttribute("aria-pressed", c === chip ? "true" : "false"); });
        closeCards(null);
        apply(chip.dataset.filter);
      });
    });
  }

  /* ---------- Admin list filter ---------- */
  var listFilter = $("#book-filter");
  if (listFilter) {
    var rows = $$("tr[data-search]");
    var noRows = $("#no-rows");
    listFilter.addEventListener("input", function () {
      var needle = listFilter.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var show = row.dataset.search.indexOf(needle) !== -1;
        row.hidden = !show;
        if (show) { shown += 1; }
      });
      if (noRows) { noRows.hidden = shown !== 0; }
    });
  }

  /* ---------- Forms that save with fetch and show the result inline ---------- */
  $$("form[data-ajax]").forEach(function (form) {
    var status = $(".form-status", form);
    var button = $("[type=submit]", form);

    function show(message, kind) {
      if (!status) { return; }
      status.textContent = message;
      status.className = "form-status " + kind;
      status.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (status) { status.textContent = ""; status.className = "form-status"; }
      var label = button.textContent;
      var redirecting = false;
      button.disabled = true;
      button.textContent = "Saving…";

      fetch(form.getAttribute("action") || window.location.href, {
        method: "POST",
        body: new FormData(form)
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (data.status === "success") {
            if (data.redirect) { redirecting = true; window.location.href = data.redirect; return; }
            show(data.message, "ok");
            if (form.hasAttribute("data-reset")) { form.reset(); }
          } else {
            show(data.message, "error");
          }
        })
        .catch(function () { show("Something went wrong. Please refresh the page and try again.", "error"); })
        .then(function () {
          if (!redirecting) { button.disabled = false; button.textContent = label; }
        });
    });
  });

  /* ---------- Cover upload preview ---------- */
  var fileInput = $("input[type=file][data-preview]");
  if (fileInput) {
    var preview = $("#" + fileInput.getAttribute("data-preview"));
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      if (file && preview) {
        preview.src = URL.createObjectURL(file);
        preview.hidden = false;
      }
    });
  }

  /* ---------- Show / hide password ---------- */
  $$("[data-toggle-password]").forEach(function (toggle) {
    toggle.addEventListener("click", function () {
      var input = $("#" + toggle.getAttribute("data-toggle-password"));
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      toggle.textContent = showing ? "Show" : "Hide";
    });
  });

  /* ---------- About page: translate the quote ---------- */
  var translate = $("[data-translate]");
  if (translate) {
    var english = false;
    translate.addEventListener("click", function () {
      english = !english;
      $$("[data-bn][data-en]").forEach(function (el) {
        el.textContent = english ? el.getAttribute("data-en") : el.getAttribute("data-bn");
      });
      translate.textContent = english ? "Show original" : "Translate";
    });
  }
})();
