// ---------- Video quiz: one question at a time, with retake ----------

var videoId = document.body.dataset.videoId;
var state = { questions: [], index: 0, answers: [], streak: 0, answered: false };

function $(id) { return document.getElementById(id); }

// Show only one screen: loading, error, quiz or result
function show(name) {
    ["loading", "error", "quiz", "result"].forEach(function (n) {
        $("screen-" + n).classList.toggle("hidden", n !== name);
    });
}

// Loads the questions (also used for "Retake quiz")
async function loadQuiz() {
    show("loading");

    try {
        var response = await fetch("/learn/api/video/" + videoId + "/quiz-data");
        var data = await response.json();

        if (!response.ok) {
            $("errorText").textContent = data.error || "Could not load the quiz.";
            show("error");
            return;
        }

        state.questions = data.questions;
        state.index = 0;
        state.answers = [];
        state.streak = 0;

        $("attemptBadge").textContent = "Attempt " + data.attempt;
        $("streakBadge").textContent = "🔥 Streak: 0";

        show("quiz");
        showQuestion();
    } catch (error) {
        $("errorText").textContent = "Could not reach the server.";
        show("error");
    }
}

function showQuestion() {
    var q = state.questions[state.index];
    state.answered = false;

    $("qCount").textContent = "Question " + (state.index + 1) + " of " + state.questions.length;
    $("progressFill").style.width = (state.index / state.questions.length * 100) + "%";
    $("questionText").textContent = q.question;
    $("feedback").classList.add("hidden");
    $("nextBtn").classList.add("hidden");

    var box = $("options");
    box.innerHTML = "";

    q.options.forEach(function (text) {
        var button = document.createElement("button");
        button.className = "option";
        button.textContent = text;
        button.onclick = function () { choose(button, q, text); };
        box.appendChild(button);
    });
}

// Student clicks an option: the server tells us if it is right
async function choose(button, q, choice) {
    if (state.answered) { return; }
    state.answered = true;

    var allButtons = document.querySelectorAll(".option");
    allButtons.forEach(function (b) { b.classList.add("done"); });

    var response = await fetch("/learn/api/video/" + videoId + "/quiz-check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: q.id, choice: choice })
    });
    var result = await response.json();

    state.answers.push({ id: q.id, choice: choice });

    var feedback = $("feedback");

    if (result.correct) {
        button.classList.add("correct");
        state.streak++;
        feedback.className = "feedback good";
        feedback.textContent = "✅ Correct! " + (result.explanation || "");
    } else {
        button.classList.add("wrong");
        state.streak = 0;
        allButtons.forEach(function (b) {
            if (b.textContent === result.answer) { b.classList.add("correct"); }
        });
        feedback.className = "feedback bad";
        feedback.textContent = "❌ Not quite. The answer is: " + result.answer + ". " + (result.explanation || "");
    }

    $("streakBadge").textContent = "🔥 Streak: " + state.streak;

    var last = state.index === state.questions.length - 1;
    $("nextBtn").textContent = last ? "See my result 🎉" : "Next →";
    $("nextBtn").classList.remove("hidden");
}

function nextQuestion() {
    state.index++;

    if (state.index < state.questions.length) {
        showQuestion();
    } else {
        finishQuiz();
    }
}

// Sends all answers to the server and shows the result
async function finishQuiz() {
    $("progressFill").style.width = "100%";

    var response = await fetch("/learn/api/video/" + videoId + "/quiz-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: state.answers })
    });
    var r = await response.json();

    var color = r.passed ? "#22c55e" : "#f59e0b";
    $("ring").style.background = "conic-gradient(" + color + " " + r.percent + "%, #e2e8f0 0)";
    $("ringText").textContent = r.percent + "%";

    if (r.passed) {
        $("resultTitle").textContent = "🎉 You passed!";
        $("resultText").textContent = "You got " + r.score + " out of " + r.total + " right. Great work!";
        $("retakeBtn").textContent = "🔄 Practise again";
        startConfetti();
    } else {
        $("resultTitle").textContent = "💪 Almost there!";
        $("resultText").textContent = "You got " + r.score + " out of " + r.total +
            " right. You need " + r.pass_percent + "% to pass. Watch the video again and retake the quiz. You can do it!";
        $("retakeBtn").textContent = "🔄 Retake quiz";
    }

    var rewardBox = $("rewardText");
    if (r.reward > 0) {
        rewardBox.textContent = "🪙 +" + r.reward + " credits earned! You now have " + r.credits + " credits.";
        rewardBox.classList.remove("hidden");
    } else {
        rewardBox.classList.add("hidden");
    }

    show("result");
}


// ---------- Small confetti celebration ----------
function startConfetti() {
    var canvas = $("confetti");
    var ctx = canvas.getContext("2d");
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    var colors = ["#6366f1", "#0ea5e9", "#22c55e", "#f59e0b", "#ec4899"];
    var pieces = [];

    for (var i = 0; i < 140; i++) {
        pieces.push({
            x: Math.random() * canvas.width,
            y: Math.random() * -canvas.height,
            size: 6 + Math.random() * 8,
            speed: 2 + Math.random() * 4,
            sway: Math.random() * 2 - 1,
            color: colors[Math.floor(Math.random() * colors.length)]
        });
    }

    var frames = 0;

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        pieces.forEach(function (p) {
            p.y += p.speed;
            p.x += p.sway;
            ctx.fillStyle = p.color;
            ctx.fillRect(p.x, p.y, p.size, p.size * 0.6);
        });
        frames++;
        if (frames < 220) {
            requestAnimationFrame(draw);
        } else {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }
    draw();
}

loadQuiz();