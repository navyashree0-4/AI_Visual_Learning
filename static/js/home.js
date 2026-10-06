// ---------- PART 1: Video preview animation (only for show) ----------

// Topics shown in the preview box
var topics = [
    {
        prompt: "Explain the OSI model in simple language.",
        scenes: [
            { emoji: "📨", title: "Why layers?", caption: "Think of sending a parcel by post" },
            { emoji: "🧱", title: "7 layers", caption: "Each layer does one small job" },
            { emoji: "🌐", title: "Real life", caption: "Your WhatsApp message uses all of them" }
        ]
    },
    {
        prompt: "Explain photosynthesis for class 8 students.",
        scenes: [
            { emoji: "☀️", title: "Sunlight", caption: "Leaves catch energy from the sun" },
            { emoji: "💧", title: "Water and CO2", caption: "Roots and air give the raw material" },
            { emoji: "🍃", title: "Food", caption: "The plant makes glucose and oxygen" }
        ]
    },
    {
        prompt: "What is a database index?",
        scenes: [
            { emoji: "📚", title: "The problem", caption: "Searching every page is slow" },
            { emoji: "🔖", title: "The index", caption: "Like the index at the end of a book" },
            { emoji: "⚡", title: "The result", caption: "Queries find data much faster" }
        ]
    }
];

var topicNumber = 0;

// Get the elements from the page
var promptBox = document.getElementById("prompt");
var emoji = document.getElementById("emoji");
var sceneTitle = document.getElementById("sceneTitle");
var caption = document.getElementById("caption");
var progressFill = document.getElementById("progressFill");

// Types the text one letter at a time
function typeText(text, whenDone) {
    var i = 0;
    promptBox.textContent = "";
    var timer = setInterval(function () {
        promptBox.textContent += text[i];
        i++;
        if (i >= text.length) {
            clearInterval(timer);
            whenDone();
        }
    }, 40);
}

// Shows the scenes one by one
function playScenes(scenes, whenDone) {
    var n = 0;

    function showNext() {
        if (n >= scenes.length) {
            whenDone();
            return;
        }
        emoji.textContent = scenes[n].emoji;
        sceneTitle.textContent = scenes[n].title;
        caption.textContent = scenes[n].caption;
        progressFill.style.width = ((n + 1) / scenes.length * 100) + "%";
        n++;
        setTimeout(showNext, 2500);
    }

    showNext();
}

// Runs one topic, then moves to the next one
function startTopic() {
    var topic = topics[topicNumber];

    // Reset the box
    emoji.textContent = "🎬";
    sceneTitle.textContent = "Creating your video...";
    caption.textContent = "";
    progressFill.style.transition = "none";
    progressFill.style.width = "0";
    setTimeout(function () {
        progressFill.style.transition = "width 2.5s linear";
    }, 50);

    typeText(topic.prompt, function () {
        playScenes(topic.scenes, function () {
            topicNumber = (topicNumber + 1) % topics.length;
            setTimeout(startTopic, 1000);
        });
    });
}

startTopic();


// ---------- PART 2: Reveal items when you scroll down ----------

var items = document.querySelectorAll(".reveal");

var watcher = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
        if (entry.isIntersecting) {
            entry.target.classList.add("show");   // makes the item visible
            watcher.unobserve(entry.target);      // only animate once
        }
    });
}, { threshold: 0.15 });

items.forEach(function (item) {
    watcher.observe(item);
});