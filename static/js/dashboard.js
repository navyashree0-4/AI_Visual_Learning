document.addEventListener("DOMContentLoaded", () => {
    "use strict";

    // --------------------------------------------------
    // HELPERS
    // --------------------------------------------------

    const $ = (selector, parent = document) =>
        parent.querySelector(selector);

    const $$ = (selector, parent = document) =>
        Array.from(parent.querySelectorAll(selector));

    const safeStorage = {
        get(key) {
            try {
                return localStorage.getItem(key);
            } catch {
                return null;
            }
        },

        set(key, value) {
            try {
                localStorage.setItem(key, value);
            } catch {
                // Storage may be unavailable.
            }
        }
    };

    // --------------------------------------------------
    // SIDEBAR / MOBILE MENU
    // --------------------------------------------------

    const sidebar = $("#sidebar");
    const menuButton = $("#menuButton");
    const scrim = $("#scrim");

    function openSidebar() {
        sidebar?.classList.add("open");
        scrim?.classList.add("active");
        document.body.classList.add("sidebar-open");
    }

    function closeSidebar() {
        sidebar?.classList.remove("open");
        scrim?.classList.remove("active");
        document.body.classList.remove("sidebar-open");
    }

    menuButton?.addEventListener("click", () => {
        if (sidebar?.classList.contains("open")) {
            closeSidebar();
        } else {
            openSidebar();
        }
    });

    scrim?.addEventListener("click", closeSidebar);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeSidebar();
        }
    });

    // Close mobile menu after clicking navigation links.
    $$(".nav-link, .logout-link").forEach(link => {
        link.addEventListener("click", closeSidebar);
    });

    // --------------------------------------------------
    // LIGHT / DARK THEME
    // --------------------------------------------------

    const themeButton = $("#themeButton");
    const themeIcon = $("#themeIcon");
    const root = document.documentElement;

    function applyTheme(theme) {
        root.dataset.theme = theme;

        if (themeIcon) {
            themeIcon.textContent = theme === "dark" ? "☀" : "☾";
        }

        safeStorage.set("eduvision-theme", theme);
    }

    const savedTheme = safeStorage.get("eduvision-theme");

    applyTheme(
        savedTheme === "light" || savedTheme === "dark"
            ? savedTheme
            : "dark"
    );

    themeButton?.addEventListener("click", () => {
        const currentTheme = root.dataset.theme || "dark";

        applyTheme(
            currentTheme === "dark" ? "light" : "dark"
        );
    });

    // --------------------------------------------------
    // PERSONALIZED GREETING
    // --------------------------------------------------

    const greeting = $("#greeting");

    if (greeting) {
        const hour = new Date().getHours();

        if (hour < 12) {
            greeting.textContent = "Good morning";
        } else if (hour < 17) {
            greeting.textContent = "Good afternoon";
        } else {
            greeting.textContent = "Good evening";
        }
    }

    // --------------------------------------------------
    // ANIMATED STATISTICS
    // --------------------------------------------------

    const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
    ).matches;

    function animateCounter(element) {
        if (!element || element.dataset.animated === "true") {
            return;
        }

        const target = Number(element.dataset.count);

        if (!Number.isFinite(target)) {
            return;
        }

        element.dataset.animated = "true";

        if (reduceMotion) {
            element.textContent = target;
            return;
        }

        const duration = 900;
        const startTime = performance.now();

        function update(now) {
            const progress = Math.min(
                (now - startTime) / duration,
                1
            );

            const eased = 1 - Math.pow(1 - progress, 3);

            element.textContent = Math.round(target * eased);

            if (progress < 1) {
                requestAnimationFrame(update);
            } else {
                element.textContent = target;
            }
        }

        requestAnimationFrame(update);
    }

    $$("[data-count]").forEach(animateCounter);

    // --------------------------------------------------
    // LEARNING PROGRESS RING
    // --------------------------------------------------

    const ring = $(".ring-fg");

    if (ring) {
        const radius = 52;
        const circumference = 2 * Math.PI * radius;

        ring.style.strokeDasharray = circumference;

        const offset = Number(ring.dataset.offset);

        ring.style.strokeDashoffset = Number.isFinite(offset)
            ? offset
            : circumference;
    }

    // --------------------------------------------------
    // WEEKLY STREAK DISPLAY
    // --------------------------------------------------

    const weekStrip = $("#weekStrip");

    if (weekStrip && !weekStrip.children.length) {
        const streak = Math.max(
            0,
            Number(weekStrip.dataset.streak) || 0
        );

        const days = ["M", "T", "W", "T", "F", "S", "S"];

        days.forEach((day, index) => {
            const item = document.createElement("span");

            item.className = "week-day";

            if (index >= 7 - Math.min(streak, 7)) {
                item.classList.add("completed");
            }

            item.textContent = day;
            weekStrip.appendChild(item);
        });
    }

    // --------------------------------------------------
    // FILE UPLOAD
    // --------------------------------------------------

    const fileInput = $("#learningFile");
    const fileMessage = $("#fileMessage");
    const uploadBox = $("#uploadBox");

    const allowedExtensions = [
        "pdf",
        "png",
        "jpg",
        "jpeg"
    ];

    function getExtension(filename) {
        return filename.split(".").pop().toLowerCase();
    }

    fileInput?.addEventListener("change", () => {
        const file = fileInput.files?.[0];

        if (!file) {
            if (fileMessage) {
                fileMessage.textContent = "No file selected.";
            }

            uploadBox?.classList.remove("file-selected");
            return;
        }

        const extension = getExtension(file.name);

        if (!allowedExtensions.includes(extension)) {
            fileInput.value = "";

            if (fileMessage) {
                fileMessage.textContent =
                    "Please select a PDF, PNG, JPG or JPEG file.";
                fileMessage.classList.add("error");
            }

            uploadBox?.classList.remove("file-selected");
            return;
        }

        if (fileMessage) {
            fileMessage.textContent = "Selected: " + file.name;
            fileMessage.classList.remove("error");
            fileMessage.classList.add("success");
        }

        uploadBox?.classList.add("file-selected");
    });

    // --------------------------------------------------
    // VIDEO GENERATION FORM
    // --------------------------------------------------

    const videoForm = $("#videoForm");
    const topicInput = $("#topic");
    const generateButton = $("#generateButton");
    const formMessage = $("#formMessage");
    const generateProgress = $("#generateProgress");
    const progressBarFill = $("#progressBarFill");
    const progressSteps = $("#progressSteps");

    function showFormMessage(message, type = "error") {
        if (!formMessage) return;

        formMessage.textContent = message;
        formMessage.className = "form-message " + type;
    }

    videoForm?.addEventListener("submit", (event) => {
        const topic = topicInput?.value.trim() || "";
        const file = fileInput?.files?.[0];

        const videoCost = Number(videoForm.dataset.cost || 10);

        const creditElement = $("#creditValue");
        const availableCredits = Number(
            creditElement?.textContent || 0
        );

        // Require a topic or uploaded study material.
        if (!topic && !file) {
            event.preventDefault();

            showFormMessage(
                "Please enter a topic or upload study material."
            );

            topicInput?.focus();
            return;
        }

        // Validate uploaded file.
        if (file) {
            const extension = getExtension(file.name);

            if (!allowedExtensions.includes(extension)) {
                event.preventDefault();

                showFormMessage(
                    "Please upload a valid PDF, PNG, JPG or JPEG file."
                );

                return;
            }
        }

        // Check available credits.
        if (availableCredits < videoCost) {
            event.preventDefault();

            showFormMessage(
                `You need ${videoCost} credits to generate a video. Your balance is ${availableCredits}.`
            );

            return;
        }

        // Allow Flask to process the form normally.
        // Do not deduct credits in JavaScript.
        showFormMessage(
            "Your video request is being submitted...",
            "success"
        );

        if (generateButton) {
            generateButton.disabled = true;

            const buttonText = $("span", generateButton);

            if (buttonText) {
                buttonText.textContent = "Creating your video...";
            }
        }

        if (generateProgress) {
            generateProgress.hidden = false;
        }

        if (progressBarFill) {
            progressBarFill.style.width = "10%";
        }

        // Visual progress indicator only.
        // Actual video generation is handled by Flask.
        if (progressSteps) {
            $$("li", progressSteps).forEach((step, index) => {
                step.classList.toggle("active", index === 0);
            });
        }
    });

    // --------------------------------------------------
    // VIDEO STYLE HINT
    // --------------------------------------------------

    const styleSelect = $("#video_style");
    const styleHint = $("#styleHint");

    const styleHints = {
        Animated:
            "🎨 Every scene gets its own image, diagram or animation-style illustration, so you understand by seeing, not just by reading.",
        "Simple Explanation":
            "💬 Plain words, short sentences and everyday examples, as if a friend is explaining it to you.",
        Storytelling:
            "📖 The topic is taught through a short story with characters, so it is easy to remember.",
        Educational:
            "🎓 A clear step-by-step lesson with definitions, key points and a summary."
    };

    function updateStyleHint() {
        if (!styleSelect || !styleHint) return;
        styleHint.textContent = styleHints[styleSelect.value] || "";
    }

    styleSelect?.addEventListener("change", updateStyleHint);
    updateStyleHint();

    // --------------------------------------------------
    // GAME SEARCH
    // --------------------------------------------------

    const gameSearch = $("#gameSearch");
    const gameGrid = $("#gameGrid");
    const gameCount = $("#gameCount");
    const noGamesMessage = $("#noGamesMessage");

    function filterGames() {
        if (!gameGrid) return;

        const searchText = (
            gameSearch?.value || ""
        ).trim().toLowerCase();

        const cards = $$(".game-card", gameGrid);

        let visibleCount = 0;

        cards.forEach(card => {
            const gameName = (
                card.dataset.name ||
                card.textContent
            ).toLowerCase();

            const matches = gameName.includes(searchText);

            card.hidden = !matches;

            if (matches) {
                visibleCount++;
            }
        });

        if (gameCount) {
            gameCount.textContent = visibleCount;
        }

        if (noGamesMessage) {
            noGamesMessage.hidden = visibleCount !== 0;
        }
    }

    gameSearch?.addEventListener("input", filterGames);

    // --------------------------------------------------
    // REVEAL SECTIONS ON SCROLL
    // --------------------------------------------------

    const revealElements = $$(".reveal");

    if ("IntersectionObserver" in window && !reduceMotion) {
        const revealObserver = new IntersectionObserver(
            (entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("is-visible");
                        observer.unobserve(entry.target);
                    }
                });
            },
            {
                threshold: 0.08
            }
        );

        revealElements.forEach(element => {
            revealObserver.observe(element);
        });
    } else {
        revealElements.forEach(element => {
            element.classList.add("is-visible");
        });
    }

    // --------------------------------------------------
    // ACTIVE NAVIGATION
    // --------------------------------------------------

    const sectionLinks = $$(
        '.nav-link[data-section]'
    );

    const trackedSections = sectionLinks
        .map(link => ({
            link,
            section: document.getElementById(
                link.dataset.section
            )
        }))
        .filter(item => item.section);

    if ("IntersectionObserver" in window) {
        const sectionObserver = new IntersectionObserver(
            entries => {
                const visibleEntries = entries
                    .filter(entry => entry.isIntersecting)
                    .sort(
                        (a, b) =>
                            b.intersectionRatio - a.intersectionRatio
                    );

                if (!visibleEntries.length) return;

                const currentId = visibleEntries[0].target.id;

                sectionLinks.forEach(link => {
                    link.classList.toggle(
                        "active",
                        link.dataset.section === currentId
                    );
                });
            },
            {
                rootMargin: "-20% 0px -65% 0px",
                threshold: [0, 0.2, 0.5]
            }
        );

        trackedSections.forEach(item => {
            sectionObserver.observe(item.section);
        });
    }

    // --------------------------------------------------
    // CREDIT BALANCE UPDATES
    // --------------------------------------------------

    function updateCredits(balance) {
        const value = Number(balance);

        if (!Number.isFinite(value)) return;

        const creditValue = $("#creditValue");
        const chipCredits = $("#chipCredits");
        const creditBalance = $("#creditBalance");
        const creditFill = $(".credit-fill");

        if (creditValue) {
            creditValue.textContent = value;
        }

        if (chipCredits) {
            chipCredits.textContent = value;
        }

        if (creditBalance) {
            creditBalance.textContent = value;
            creditBalance.dataset.count = value;
        }

        if (creditFill) {
            const percentage = Math.min(
                Math.max(value, 0),
                100
            );

            creditFill.style.width = percentage + "%";
        }
    }

    function handleCreditEvent(event) {
        const detail = event.detail;

        if (typeof detail === "number") {
            updateCredits(detail);
            return;
        }

        if (!detail || typeof detail !== "object") {
            return;
        }

        if (detail.balance !== undefined) {
            updateCredits(detail.balance);
        } else if (detail.credits !== undefined) {
            updateCredits(detail.credits);
        }
    }

    document.addEventListener(
        "eduvision:credits-updated",
        handleCreditEvent
    );

    document.addEventListener(
        "eduvision:credits-earned",
        handleCreditEvent
    );

    // --------------------------------------------------
    // SCROLL PROGRESS
    // --------------------------------------------------

    const scrollProgress = $("#scrollProgress");

    function updateScrollProgress() {
        if (!scrollProgress) return;

        const scrollableHeight =
            document.documentElement.scrollHeight -
            window.innerHeight;

        if (scrollableHeight <= 0) {
            scrollProgress.style.width = "0%";
            return;
        }

        const percentage =
            (window.scrollY / scrollableHeight) * 100;

        scrollProgress.style.width =
            Math.min(percentage, 100) + "%";
    }

    window.addEventListener(
        "scroll",
        updateScrollProgress,
        { passive: true }
    );

    updateScrollProgress();

    // --------------------------------------------------
    // TILT EFFECT FOR CARDS
    // --------------------------------------------------

    const canHover = window.matchMedia(
        "(hover: hover) and (pointer: fine)"
    ).matches;

    if (canHover && !reduceMotion) {
        $$(".tilt").forEach(card => {
            card.addEventListener("mousemove", event => {
                const rect = card.getBoundingClientRect();

                const x =
                    (event.clientX - rect.left) / rect.width;

                const y =
                    (event.clientY - rect.top) / rect.height;

                const rotateY = (x - 0.5) * 4;
                const rotateX = (0.5 - y) * 4;

                card.style.transform =
                    `perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-3px)`;
            });

            card.addEventListener("mouseleave", () => {
                card.style.transform = "";
            });
        });
    }

    // --------------------------------------------------
    // FINISH
    // --------------------------------------------------

    console.log("EduVision dashboard loaded successfully.");

});