
"use strict";

/* =====================================================
   EDUVISION APTITUDE ARENA
   File: static/js/aptitude.js
   ===================================================== */

document.addEventListener("DOMContentLoaded", () => {

    // Read the configuration provided by aptitude_test.html
    const configElement = document.getElementById("aptitude-config");

    window.aptitudeTestConfig = configElement
        ? JSON.parse(configElement.textContent)
        : {
            durationSeconds: 1800,
            questionCount: 0
        };

    const testForm = document.getElementById("aptitudeTestForm");

    // The arena page does not contain the test form.
    if (!testForm) {
        return;
    }

    const panels = Array.from(
        testForm.querySelectorAll(".question-panel")
    );

    const questionButtons = Array.from(
        document.querySelectorAll(".question-number")
    );

    const questionNumber = document.getElementById("questionNumber");
    const progressBar = document.getElementById("questionProgress");
    const previousButton = document.getElementById("previousQuestion");
    const nextButton = document.getElementById("nextQuestion");
    const submitButton = document.getElementById("submitTest");
    const countdownElement = document.getElementById("countdown");
    const timerCard = document.getElementById("timerCard");
    const timeTakenInput = document.getElementById("timeTaken");

    const config = window.aptitudeTestConfig || {};
    const durationSeconds = Math.max(
        1,
        Number(config.durationSeconds) || 1800
    );

    // Keep the rest of your existing JavaScript below this line.
