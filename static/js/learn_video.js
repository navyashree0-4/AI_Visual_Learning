// ---------- Ask a question about the video ----------

var videoId = document.body.dataset.videoId;
var chatBox = document.getElementById("chatBox");
var input = document.getElementById("questionInput");
var askBtn = document.getElementById("askBtn");

// Scroll the chat to the newest message
chatBox.scrollTop = chatBox.scrollHeight;

// Put a ready-made question into the box and send it
function useIdea(text) {
    input.value = text;
    askQuestion();
}

// Add one chat bubble ("me" or "ai")
function addBubble(text, who) {
    var empty = document.getElementById("chatEmpty");
    if (empty) { empty.remove(); }

    var bubble = document.createElement("div");
    bubble.className = "bubble " + who;
    bubble.textContent = text;          // textContent keeps it safe
    chatBox.appendChild(bubble);
    chatBox.scrollTop = chatBox.scrollHeight;
    return bubble;
}

async function askQuestion() {
    var question = input.value.trim();
    if (question.length < 3) { return; }

    addBubble(question, "me");
    input.value = "";
    askBtn.disabled = true;

    var waiting = addBubble("Thinking...", "ai");

    try {
        var response = await fetch("/learn/api/video/" + videoId + "/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: question })
        });
        var data = await response.json();
        waiting.textContent = data.answer || data.error || "Sorry, something went wrong.";
    } catch (error) {
        waiting.textContent = "Could not reach the server. Please try again.";
    }

    askBtn.disabled = false;
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Pressing Enter sends the question
input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { askQuestion(); }
});


// When the page is opened from "Ask a question" on the dashboard, jump to the box
if (window.location.hash === "#ask") {
    document.getElementById("ask").scrollIntoView();
    input.focus();
}