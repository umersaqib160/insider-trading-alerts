(function () {
  "use strict";
  var root = document.documentElement;
  var KEY = "btc-theme";
  var darkMq = window.matchMedia("(prefers-color-scheme: dark)");

  function storedMode() {
    try { var m = localStorage.getItem(KEY); return m === "light" || m === "dark" ? m : "system"; } catch (e) { return "system"; }
  }
  function applyTheme() {
    var mode = storedMode();
    if (mode === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", mode);
    var dark = mode === "dark" || (mode === "system" && darkMq.matches);
    var btn = document.getElementById("theme-btn");
    if (btn) {
      btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      btn.querySelector("use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
    }
    var radio = document.getElementById("th-" + mode);
    if (radio) radio.checked = true;
  }
  function setTheme(mode) {
    try { localStorage.setItem(KEY, mode); } catch (e) { /* storage unavailable: theme lasts for this page only */ }
    if (mode === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", mode);
    applyTheme();
  }

  var toastTimer = 0;
  function toast(message) {
    var el = document.getElementById("toast");
    if (!el || !message) return;
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3600);
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme();
    var btn = document.getElementById("theme-btn");
    if (btn) btn.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme") === "dark" || (!root.hasAttribute("data-theme") && darkMq.matches);
      setTheme(dark ? "light" : "dark");
    });
    document.querySelectorAll('input[name="theme"]').forEach(function (r) {
      r.addEventListener("change", function () { setTheme(r.value); });
    });
  });
  darkMq.addEventListener("change", applyTheme);

  document.body.addEventListener("showToast", function (e) { toast(e.detail && e.detail.message); });
  document.body.addEventListener("htmx:responseError", function () { toast("Something went wrong. Try again."); });
  document.body.addEventListener("htmx:sendError", function () { toast("Couldn't reach the server. Check your connection."); });
})();
