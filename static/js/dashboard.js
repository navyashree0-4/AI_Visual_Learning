/* EduVision dashboard: views, greeting, theme, menu, counters, search, streak labels. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var root = document.documentElement;

  /* Greeting by time of day */
  var greeting = $("greeting");
  if (greeting) {
    var h = new Date().getHours();
    greeting.textContent = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }

  /* Theme toggle (remembered in this browser) */
  var themeBtn = $("themeButton");
  var themeIcon = $("themeIcon");
  function showTheme() { if (themeIcon) themeIcon.textContent = root.dataset.theme === "light" ? "☀" : "☾"; }
  showTheme();
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem("eduvision-theme", root.dataset.theme); } catch (e) {}
      showTheme();
    });
  }

  /* Mobile sidebar */
  var sidebar = $("sidebar");
  var scrim = $("scrim");
  var menuBtn = $("menuButton");
  function setMenu(open) {
    if (!sidebar || !scrim) return;
    sidebar.classList.toggle("open", open);
    scrim.classList.toggle("show", open);
    if (menuBtn) menuBtn.setAttribute("aria-expanded", open);
  }
  if (menuBtn) menuBtn.addEventListener("click", function () { setMenu(!sidebar.classList.contains("open")); });
  if (scrim) scrim.addEventListener("click", function () { setMenu(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setMenu(false); });
  if (sidebar) sidebar.addEventListener("click", function (e) { if (e.target.closest("a")) setMenu(false); });

  /* Views: "#my-videos" shows the full video library, everything else shows the home page */
  var crumb = $("crumb");
  function applyView(scroll) {
    var hash = location.hash;
    var view = hash === "#my-videos" ? "videos" : "home";
    root.dataset.view = view;

    var activeKey = view === "videos" ? "videos" : (hash && hash !== "#home" ? hash.slice(1) : "home");
    document.querySelectorAll(".nav-link[data-nav]").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-nav") === activeKey);
    });
    if (crumb) crumb.textContent = view === "videos" ? "My generated videos" : "Dashboard";

    if (!scroll) return;
    var target = view === "home" && hash && hash !== "#home" ? document.getElementById(hash.slice(1)) : null;
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", function () { applyView(true); });
  applyView(false);
  if (location.hash && location.hash !== "#my-videos" && location.hash !== "#home") applyView(true);

  /* Count-up for stat numbers (skipped if the user prefers reduced motion) */
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduce) {
    document.querySelectorAll("[data-count]").forEach(function (el) {
      var target = parseInt(el.getAttribute("data-count"), 10);
      if (!target || target < 1) return;
      var start = null;
      function step(t) {
        if (start === null) start = t;
        var p = Math.min((t - start) / 800, 1);
        el.textContent = Math.round(target * p);
        if (p < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }

  /* Search your videos */
  var videoSearch = $("videoSearch");
  var videosGrid = $("videosGrid");
  var videoCount = $("videoCount");
  var videoEmpty = $("videoEmpty");
  if (videoSearch && videosGrid) {
    videoSearch.addEventListener("input", function () {
      var q = videoSearch.value.trim().toLowerCase();
      var shown = 0;
      videosGrid.querySelectorAll(".video-card").forEach(function (card) {
        var match = !q || (card.getAttribute("data-title") || "").indexOf(q) !== -1;
        card.style.display = match ? "" : "none";
        if (match) shown++;
      });
      if (videoCount) videoCount.textContent = shown;
      if (videoEmpty) videoEmpty.hidden = shown !== 0;
    });
  }

  /* Game search */
  var search = $("gameSearch");
  var gameGrid = $("gameGrid");
  var count = $("gameCount");
  var none = $("noGamesMessage");
  if (search && gameGrid) {
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      var shown = 0;
      gameGrid.querySelectorAll(".game-card").forEach(function (card) {
        var match = !q || (card.getAttribute("data-name") || "").indexOf(q) !== -1;
        card.style.display = match ? "" : "none";
        if (match) shown++;
      });
      if (count) count.textContent = shown;
      if (none) none.hidden = shown !== 0;
    });
  }

  /* Weekday names under the 7-day streak row */
  document.querySelectorAll("#streakWeek .streak-day").forEach(function (day) {
    var offset = parseInt(day.getAttribute("data-offset"), 10);
    if (!offset) return;
    var d = new Date();
    d.setDate(d.getDate() - offset);
    var label = day.querySelector("span");
    if (label) label.textContent = d.toLocaleDateString(undefined, { weekday: "short" });
  });
})();