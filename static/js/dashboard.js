/* EduVision dashboard script - matches templates/dashboard.html
   Handles: theme toggle, mobile menu, greeting, scroll progress,
   reveal-on-scroll and number count-up. Nothing else is injected into the page. */
(function () {
    "use strict";

    var root = document.documentElement;
    var reduceMotion = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ---------- Theme ---------- */
    var themeButton = document.getElementById("themeButton");
    var themeIcon = document.getElementById("themeIcon");

    function applyTheme(theme) {
        root.dataset.theme = theme;
        if (themeIcon) themeIcon.textContent = theme === "dark" ? "☾" : "☀";
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute("content", theme === "dark" ? "#14122e" : "#f4f5fb");
    }

    applyTheme(root.dataset.theme || "dark");

    if (themeButton) {
        themeButton.addEventListener("click", function () {
            var next = root.dataset.theme === "dark" ? "light" : "dark";
            applyTheme(next);
            try { localStorage.setItem("eduvision-theme", next); } catch (e) {}
        });
    }

    /* ---------- Mobile sidebar ---------- */
    var sidebar = document.getElementById("sidebar");
    var scrim = document.getElementById("scrim");
    var menuButton = document.getElementById("menuButton");

    function setMenu(open) {
        if (!sidebar || !scrim) return;
        sidebar.classList.toggle("open", open);
        scrim.classList.toggle("show", open);
    }

    if (menuButton) {
        menuButton.addEventListener("click", function () {
            setMenu(!sidebar.classList.contains("open"));
        });
    }
    if (scrim) scrim.addEventListener("click", function () { setMenu(false); });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") setMenu(false);
    });
    if (sidebar) {
        sidebar.addEventListener("click", function (e) {
            if (e.target.closest(".nav-link")) setMenu(false);
        });
    }

    /* ---------- Greeting ---------- */
    var greeting = document.getElementById("greeting");
    if (greeting) {
        var hour = new Date().getHours();
        greeting.textContent =
            hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    }

    /* ---------- Scroll progress bar ---------- */
    var progress = document.getElementById("scrollProgress");
    function updateProgress() {
        if (!progress) return;
        var max = document.documentElement.scrollHeight - window.innerHeight;
        progress.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + "%";
    }
    window.addEventListener("scroll", updateProgress, { passive: true });
    updateProgress();

    /* ---------- Reveal on scroll ---------- */
    var revealItems = document.querySelectorAll(".reveal");
    if ("IntersectionObserver" in window && !reduceMotion) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08 });
        revealItems.forEach(function (el) { observer.observe(el); });
    } else {
        revealItems.forEach(function (el) { el.classList.add("visible"); });
    }

    /* ---------- Count-up numbers ---------- */
    if (!reduceMotion) {
        document.querySelectorAll("[data-count]").forEach(function (el) {
            var target = parseInt(el.getAttribute("data-count"), 10);
            if (isNaN(target) || target <= 0) return;
            var start = null, duration = 800;
            function step(ts) {
                if (start === null) start = ts;
                var t = Math.min((ts - start) / duration, 1);
                el.textContent = Math.round(target * t);
                if (t < 1) requestAnimationFrame(step);
            }
            el.textContent = "0";
            requestAnimationFrame(step);
        });
    }

    /* ---------- Sidebar: highlight "My Generated Videos" when jumping to it ---------- */
    var libraryLink = document.querySelector('.nav-link[data-section="my-videos"]');
    if (libraryLink) {
        libraryLink.addEventListener("click", function (e) {
            var target = document.getElementById("my-videos");
            if (!target) return;
            e.preventDefault();
            target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
        });
    }
})();