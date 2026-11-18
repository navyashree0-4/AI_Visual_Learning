"""
services/video_generator.py
EduVision Video Generator Service
- Includes extract_text, generate_video_package, and ai_status for app.py
- Glowing blue animated lesson look: title intro, robot teacher, numbered point pills (NO pointer arrows),
  synced captions that explain the lesson
"""
import asyncio
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

logger = logging.getLogger("video_generator")

# ==================================================
# 1. CONFIGURATION
# ==================================================
_HERE = Path(__file__).resolve().parent
BASE_DIR = _HERE.parent if _HERE.name.lower() == "services" else _HERE
if load_dotenv:
    load_dotenv(BASE_DIR / ".env", override=False, encoding="utf-8-sig")


def _env_int(name, default, low=None, high=None):
    try:
        v = int(float(os.getenv(name, "") or default))
    except ValueError:
        v = default
    if low is not None:
        v = max(low, v)
    if high is not None:
        v = min(high, v)
    return v


GENERATED_DIR = BASE_DIR / "static" / "generated"
TEMP_DIR = GENERATED_DIR / "temp"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_FALLBACKS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-2.5-flash-lite").split(",")
    if m.strip()
]
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
USER_AGENT = "EduVision/1.0 (educational project)"

FPS = _env_int("FPS", 6, 4, 15)
CRF = str(_env_int("CRF", 23, 14, 32))
RENDER_WIDTH = _env_int("RENDER_WIDTH", 1280, 480, 1920)
RENDER_WORKERS = _env_int("RENDER_WORKERS", 3, 1, 8)
PHOTO_BUDGET = _env_int("PHOTO_BUDGET_SECONDS", 8, 3, 60)
MIN_PHOTO_W, MIN_PHOTO_H = 640, 360
MAX_MINUTES = _env_int("UI_MAX_MINUTES", 10, 1, 60)
# Names app.py imports (video length limits and script mode).
UI_MAX_MINUTES = MAX_MINUTES
DEFAULT_MINUTES = 3
USE_ALGOS = False
SCRIPT_MODE = (os.getenv("EDUVISION_SCRIPT_MODE", "ai").strip().lower() or "ai")
PAUSE = 0.7
INTRO_SECONDS = 3
SECONDS_PER_SCENE = 25

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280)}
WORDS_PER_MINUTE = {"english": 150, "kannada": 115, "hindi": 135}
LANG_KEYS = {"english": "English", "kannada": "Kannada", "hindi": "Hindi"}
SCRIPT_RANGES = {"kannada": (0x0C80, 0x0CFF), "hindi": (0x0900, 0x097F)}
LANG_CODES = {"english": "en", "kannada": "kn", "hindi": "hi"}
LANGUAGE_NOTE = {
    "english": "Write everything in clear English.",
    "kannada": "Write everything in Kannada script (ಕನ್ನಡ). No English letters, no English answer. Natural spoken Kannada like a teacher.",
    "hindi": "Write everything in Hindi Devanagari script (देवनागरी). No Hinglish, no English answer. Simple spoken Hindi like a teacher.",
}

AUDIENCES = ["Kids", "School Students", "College Students", "Teachers"]
LEVELS = ["Beginner", "Intermediate", "Advanced"]
AUDIENCE_TAG = {
    "Kids": "Kids Level",
    "School Students": "School Level",
    "College Students": "College Level",
    "Teachers": "Teachers Level",
}
DEFAULT_LEVEL = {
    "Kids": "Beginner",
    "School Students": "Beginner",
    "College Students": "Intermediate",
    "Teachers": "Advanced",
}
LEVEL_LABELS = {"Beginner": 3, "Intermediate": 4, "Advanced": 5}
LEVEL_WORDS = {"Beginner": 0.9, "Intermediate": 1.0, "Advanced": 1.15}

TEACHING_RULES = {
    ("Kids", "Beginner"): "Very simple words, short sentences, playful comparisons, friendly tone.",
    ("Kids", "Intermediate"): "Simple clear steps with fun examples from daily life.",
    ("Kids", "Advanced"): "Clear explanation of how things work with simple science examples.",
    ("School Students", "Beginner"): "Very simple words, short sentences (under 14 words). Familiar objects (lunch box, cricket ball). Explain every new word. Friendly, encouraging, no jargon, no formulas.",
    ("School Students", "Intermediate"): "Explain HOW and WHY it works. Introduce the correct terms with a short definition. Use school-science examples and connect to daily life.",
    ("School Students", "Advanced"): "School-curriculum depth: explain processes and relationships in detail, include a formula or measurement where relevant, mention one common misconception and one practical application.",
    ("College Students", "Beginner"): "Introduce the topic and why it matters. Define fundamentals, name the components and the basic working principle. Introduce technical terms gradually with practical examples.",
    ("College Students", "Intermediate"): "Explain internal mechanism step by step (architecture, algorithm or process). Give industry examples, then advantages, disadvantages and applications.",
    ("College Students", "Advanced"): "University-level: theoretical foundations, formulas / models / pseudocode where relevant, complexity, optimisation, limitations, alternative approaches, real-world applications. Academic and precise.",
    ("Teachers", "Beginner"): "Explain how to introduce this topic in class: one learning objective, simple teaching explanation, a visual teaching aid, and a question to ask students.",
    ("Teachers", "Intermediate"): "Structured lesson: introduction, teaching, demonstration, conclusion. Include a classroom activity, a common student misunderstanding and a way to check understanding.",
    ("Teachers", "Advanced"): "Professional teaching depth: detailed academic concepts, differentiated teaching strategies, common learning difficulties and how to fix them, an activity, a critical-thinking question and an assessment method.",
}

STYLE_RULES = {
    "Educational": "Calm professional teacher giving a lecture: define the key term, explain the steps in order, then a real-world example. Say what to look at in the picture.",
    "Storytelling": "ONE continuing story with two named characters. Each scene is one story beat in a concrete visible place that also explains the real concept. Happy ending that sums up the lesson.",
    "Simple Explanation": "Talk to a complete beginner. One idea per scene, one familiar comparison, every hard word explained at once.",
    "Presenter": "A friendly presenter speaking to the viewer: greeting in scene 1, natural spoken sentences, a one-sentence takeaway at the end.",
}


def pick(value, valid, default):
    text = str(value or "").strip().lower()
    for item in valid:
        if text == item.lower():
            return item
    for item in valid:
        if item.lower().split()[0] in text:
            return item
    return default


def normalize_style(style):
    t = str(style or "").lower()
    if "present" in t:
        return "Presenter"
    if "story" in t or "cartoon" in t or "anim" in t:
        return "Storytelling"
    if "simple" in t:
        return "Simple Explanation"
    return "Educational"


# ==================================================
# 2. TEXT EXTRACTION (Required by app.py)
# ==================================================
def extract_text(file_path):
    """Extracts plain text from PDF, TXT, or Markdown files."""
    if not file_path:
        return ""
    path = Path(file_path)
    if not path.exists():
        return ""
    ext = path.suffix.lower()
    if ext == ".pdf":
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is not installed. Run: pip install pymupdf")
        chunks = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                txt = page.get_text("text").strip()
                if txt:
                    chunks.append(txt)
        return "\n\n".join(chunks).strip()
    return path.read_text(encoding="utf-8", errors="ignore").strip()


# ==================================================
# 3. AI TEXT & STATUS (Gemini -> Ollama)
# ==================================================
_SYSTEM = (
    "You are an expert teacher and educational video director. Create accurate, engaging content "
    "for students. Never invent facts. Always return valid JSON only."
)


def _post_json(url, payload, headers=None, timeout=60):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _gemini(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError("No GEMINI_API_KEY")
    last = None
    for model in [GEMINI_MODEL] + GEMINI_FALLBACKS:
        cfg = {"temperature": 0.5, "maxOutputTokens": 8192, "responseMimeType": "application/json"}
        if "2.5" in model:
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        body = {
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": cfg,
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                res = _post_json(url, body, {"x-goog-api-key": GEMINI_API_KEY}, timeout=60)
                parts = ((res.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                text = "".join(str(p.get("text", "")) for p in parts).strip()
                if text:
                    return text
                last = RuntimeError("Gemini returned an empty answer")
                break
            except urllib.error.HTTPError as exc:
                last = RuntimeError(f"Gemini HTTP {exc.code}")
                if exc.code in (500, 503) and attempt == 0:
                    time.sleep(2)
                    continue
                break
            except Exception as exc:
                last = exc
                break
    raise last or RuntimeError("Gemini failed")


def _ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "keep_alive": "20m",
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        "options": {"temperature": 0.5, "num_ctx": 6144, "num_predict": 4500},
    }
    res = _post_json(OLLAMA_URL, payload, timeout=900)
    text = res.get("message", {}).get("content", "")
    if not text:
        raise RuntimeError("Ollama returned an empty answer")
    return text


def _parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


_ai_off_until = [0.0]


def ask_json(prompt):
    errors = []
    engines = []
    if GEMINI_API_KEY and time.time() >= _ai_off_until[0]:
        engines.append(("Gemini", _gemini))
    engines.append(("Ollama", _ollama))
    for name, fn in engines:
        gemini_failed = False
        for _ in range(2):
            try:
                data = _parse_json(fn(prompt))
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:120]}")
                gemini_failed = name == "Gemini"
                if name == "Ollama" and isinstance(exc, (urllib.error.URLError, ConnectionError)):
                    break
        if gemini_failed:
            _ai_off_until[0] = time.time() + 120
    raise RuntimeError("No AI model answered (" + "; ".join(errors[-3:]) + ")")


def _ollama_reachable():
    try:
        base = OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags"
        with urllib.request.urlopen(base, timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
        return any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL.split(":")[0] for n in names)
    except Exception:
        return False


def ai_available():
    if GEMINI_API_KEY and time.time() >= _ai_off_until[0]:
        return True
    return _ollama_reachable()


def ai_status():
    """Returns engine availability dictionary required by app.py."""
    gemini_ok = bool(GEMINI_API_KEY and time.time() >= _ai_off_until[0])
    ollama_ok = _ollama_reachable()
    return {
        "gemini": gemini_ok,
        "ollama": ollama_ok,
        "available": gemini_ok or ollama_ok,
        "active_engine": "gemini" if gemini_ok else ("ollama" if ollama_ok else "algorithm"),
        "tts": "edge-tts" if edge_tts_available() else "gtts",
    }


# ==================================================
# 4. SCRIPT GENERATION
# ==================================================
def _tidy(v):
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v)
    return re.sub(r"\s+", " ", re.sub(r"[*#_`>\[\]]+", " ", str(v or ""))).strip()


def _script_ratio(text, language):
    rng = SCRIPT_RANGES.get(language.lower())
    letters = [c for c in str(text or "") if c.isalpha()]
    if not rng or not letters:
        return 1.0
    return sum(1 for c in letters if rng[0] <= ord(c) <= rng[1]) / len(letters)


def _clean_scene(sc, language, n_labels):
    if not isinstance(sc, dict):
        return None
    title, narration = _tidy(sc.get("title")), _tidy(sc.get("narration"))
    if not title or len(narration.split()) < 8:
        return None
    labels = [_tidy(x)[:36] for x in (sc.get("labels") or []) if _tidy(x)][:n_labels]
    if len(labels) < 2:
        parts = [p.strip() for p in re.split(r"(?<=[.!?।॥])\s+", narration) if p.strip()]
        labels = [" ".join(p.split()[:4]) for p in parts[:n_labels]]
    if len(labels) < 2:
        labels = (labels + [title, title])[:2]
    kt = sc.get("key_term") if isinstance(sc.get("key_term"), dict) else {}
    term = {"term": _tidy(kt.get("term"))[:40], "definition": _tidy(kt.get("definition"))[:140]}
    q = str(sc.get("image_query") or "").replace('"', " ").replace("'", " ").replace("\n", " ").replace("\r", " ").strip()[:60]
    qa = str(sc.get("image_query_alt") or "").replace('"', " ").replace("'", " ").replace("\n", " ").replace("\r", " ").strip()[:40]
    return {
        "title": title[:80],
        "narration": narration,
        "labels": labels,
        "key_term": term,
        "image_query": q,
        "image_query_alt": qa,
    }


def plan_length(minutes, language, difficulty):
    total = max(30.0, minutes * 60.0)
    n = max(4, min(60, int(round(total / SECONDS_PER_SCENE))))
    wpm = WORDS_PER_MINUTE.get(language.lower(), 140)
    words = int((total - n * PAUSE) / 60.0 * wpm / n * LEVEL_WORDS[difficulty])
    return n, max(25, words)


def write_script_ai(topic, source, audience, difficulty, language, style, n, words, progress=None):
    n_labels = LEVEL_LABELS[difficulty]
    rules = TEACHING_RULES.get((audience, difficulty), TEACHING_RULES[("School Students", "Beginner")])
    scenes, title, rounds = [], "", 0
    per = 6
    while len(scenes) < n and rounds < n + 6:
        rounds += 1
        first = len(scenes)
        count = min(per, n - first)
        covered = "; ".join(s["title"] for s in scenes) or "none yet"
        last_note = (
            "The LAST scene is the final summary of the important points with a meaningful conclusion"
            + (
                " plus one classroom activity and one check-for-understanding question."
                if audience == "Teachers"
                else "."
            )
            if first + count >= n
            else "Do NOT write the final summary yet."
        )
        first_note = (
            f"Scene 1: its title is the question 'What is {topic}?' (in {language}) and its narration "
            "starts with a plain definition, then a hook from real life and the learning objective."
            if first == 0
            else ""
        )
        src = f"\nSOURCE MATERIAL (use its facts, never invent):\n{source[:5000]}\n" if source else ""
        prompt = f"""
Write scenes {first + 1} to {first + count} of a {n}-scene classroom video about: {topic}
{src}
AUDIENCE: {audience}.  LEVEL: {difficulty}.  TEACHING RULES: {rules}
STYLE: {style}. {STYLE_RULES[style]}
LANGUAGE: {language}. {LANGUAGE_NOTE[language.lower()]}

Video order: hook + objectives -> basic concept -> step-by-step explanation (one idea per scene, each with a real-life
example) -> demonstrations -> applications / common mistakes -> summary. Do not repeat scenes.
Already written (do not repeat): {covered}
{first_note} {last_note}

Rules for every scene:
- title: a short question or a 3 to 5 word phrase about ONE idea, in {language}.
- narration: about {words} words, spoken teacher voice, plain sentences for text-to-speech, no Markdown, no lists.
  The FIRST sentence is a plain, clear definition or answer in simple words. Mention what to look at in the picture.
  Match the audience and level exactly.
- image_query: ENGLISH 2-5 words for ONE real photograph of a concrete visible subject (never abstract words).
  image_query_alt: ENGLISH 1-3 words, the main object.
- labels: exactly {n_labels} key points, each at most 4 words, in the order the narration mentions them, in {language}.
- key_term: one important term with a one-sentence definition, in {language}.

Return JSON exactly like this:
{{"title": "Video title in {language}",
  "scenes": [{{"title": "...", "narration": "...", "image_query": "green leaf sunlight",
              "image_query_alt": "green leaf", "labels": ["one", "two", "three"],
              "key_term": {{"term": "...", "definition": "..."}}}}]}}
"""
        data = ask_json(prompt)
        title = title or _tidy(data.get("title"))
        for sc in data.get("scenes") or []:
            c = _clean_scene(sc, language, n_labels)
            if c and _script_ratio(c["narration"], language) >= 0.6:
                scenes.append(c)
                if len(scenes) >= n:
                    break
        if progress:
            progress(len(scenes) / n, "Writing the lesson")
    if len(scenes) < max(3, n // 2):
        raise RuntimeError(f"The AI could not write the lesson in {language}.")
    return title or topic, scenes


_STOP = set(
    """a an the of in on and with for to is are was were be been being that this these those it its as at by from or
not but can will which who whom what when where how why also into than then there their they them have has had do does did
such more most other some any all each both between about over under after before during while using used use may might""".split()
)


def _wikipedia_text(topic, max_chars=9000):
    try:
        qs = urllib.parse.urlencode(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": topic,
                "gsrlimit": 1,
                "prop": "extracts",
                "explaintext": 1,
                "exlimit": 1,
                "format": "json",
                "redirects": 1,
            }
        )
        req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + qs, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            pages = (json.loads(r.read().decode()).get("query") or {}).get("pages") or {}
        text = next(iter(pages.values()), {}).get("extract", "")
        return re.sub(r"\n=+ [^=]+ =+\n", "\n", text)[:max_chars].strip()
    except Exception:
        logger.warning("Wikipedia lookup failed", exc_info=True)
        return ""


@lru_cache(maxsize=1)
def _translator_ok():
    try:
        import deep_translator  # noqa: F401
        return True
    except ImportError:
        return False


def _translate(text, target):
    from deep_translator import GoogleTranslator

    parts, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", str(text)):
        if cur and len(cur) + len(s) > 3500:
            parts.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        parts.append(cur)
    return " ".join(GoogleTranslator(source="en", target=target).translate(p) or p for p in parts)


def write_script_algo(topic, source, audience, difficulty, language, n, words):
    text = source or ""
    if len(text.split()) < 120:
        text = _wikipedia_text(topic) or text
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if len(s.split()) >= 6]
    if len(sentences) < 6:
        raise RuntimeError(
            "No AI model is running and no source text could be found for this topic. "
            "Add GEMINI_API_KEY, start Ollama, or paste some text about the topic."
        )
    if language.lower() != "english" and not _translator_ok():
        raise RuntimeError(f"{language} needs an AI model (Gemini / Ollama) or: pip install deep-translator")
    n = max(3, min(n, len(sentences) // 2))
    per_words = max(25, words)
    groups, cur, cnt = [], [], 0
    for s in sentences:
        if len(groups) >= n:
            break
        cur.append(s)
        cnt += len(s.split())
        if cnt >= per_words:
            groups.append(cur)
            cur, cnt = [], 0
    if cur and len(groups) < n:
        groups.append(cur)
    n_labels = LEVEL_LABELS[difficulty]
    scenes = []
    for i, g in enumerate(groups):
        narr = " ".join(g)
        freq = {}
        for w in re.findall(r"[A-Za-z][A-Za-z\-]{4,}", narr):
            if w.lower() not in _STOP:
                freq[w.lower()] = freq.get(w.lower(), 0) + 1
        keys = [k for k, _ in sorted(freq.items(), key=lambda kv: -kv[1])][:n_labels]
        while len(keys) < 2:
            keys.append(topic.lower())
        if i == 0:
            ttl = f"What is {topic}?"
        elif i == len(groups) - 1:
            ttl = "Summary"
        else:
            ttl = keys[0].capitalize()
        first_def = next((s for s in g if re.search(r"\b(is|are|refers to|means)\b", s)), g[0])
        scenes.append(
            {
                "title": ttl,
                "narration": narr,
                "labels": [k.capitalize() for k in keys],
                "key_term": {"term": keys[0].capitalize(), "definition": first_def[:140]},
                "image_query": topic if i == 0 else f"{keys[0]} {topic}",
                "image_query_alt": topic,
            }
        )
    title = topic[:1].upper() + topic[1:]
    if language.lower() != "english":
        tgt = LANG_CODES[language.lower()]
        for sc in scenes:
            for k in ("title", "narration"):
                sc[k] = _translate(sc[k], tgt)
            sc["labels"] = [_translate(x, tgt) for x in sc["labels"]]
            sc["key_term"] = {
                "term": _translate(sc["key_term"]["term"], tgt),
                "definition": _translate(sc["key_term"]["definition"], tgt),
            }
        title = _translate(title, tgt)
    return title, scenes


def build_script(topic, source, audience, difficulty, language, style, minutes, progress=None):
    n, words = plan_length(minutes, language, difficulty)
    if ai_available():
        try:
            title, scenes = write_script_ai(topic, source, audience, difficulty, language, style, n, words, progress)
            return title, scenes, "ai"
        except Exception as exc:
            logger.warning("AI script failed (%s). Using the built-in algorithm.", exc)
    title, scenes = write_script_algo(topic, source, audience, difficulty, language, n, words)
    return title, scenes, "algorithm"


# ==================================================
# 5. VOICE CREATION
# ==================================================
VOICES = {
    "english": {
        "female": ["en-US-AvaMultilingualNeural", "en-US-JennyNeural", "en-IN-NeerjaNeural"],
        "male": ["en-US-AndrewMultilingualNeural", "en-US-GuyNeural", "en-IN-PrabhatNeural"],
    },
    "kannada": {"female": ["kn-IN-SapnaNeural"], "male": ["kn-IN-GaganNeural"]},
    "hindi": {"female": ["hi-IN-SwaraNeural"], "male": ["hi-IN-MadhurNeural"]},
}
VOICE_RATE = {"Kids": -5, "School Students": -4, "College Students": 0, "Teachers": -2}
_tts_stats = {"fallbacks": 0}
_tts_lock = threading.Lock()


@lru_cache(maxsize=1)
def edge_tts_available():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def voice_names(language, voice):
    gender = "male" if str(voice).lower().startswith("m") else "female"
    return VOICES[language.lower()][gender]


def _clean_for_speech(text):
    text = re.sub(r"https?://\S+", " ", str(text or ""))
    text = text.replace("&", " and ").replace("%", " percent ")
    text = re.sub(r"[*#_`>\[\]{}|~^]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def generate_narration(text, out_path, language="English", voice="Female", rate_pct=0):
    text = _clean_for_speech(text)
    if not text:
        raise ValueError("Narration text is empty.")
    out = Path(out_path)
    last = None
    if edge_tts_available():
        import edge_tts

        async def run(name):
            await edge_tts.Communicate(text, name, rate=f"{int(rate_pct):+d}%").save(str(out))

        for name in voice_names(language, voice):
            for attempt in range(2):
                try:
                    asyncio.run(run(name))
                    if out.exists() and out.stat().st_size > 0:
                        return str(out)
                except Exception as exc:
                    last = exc
                    time.sleep(0.4 * (attempt + 1))
    if str(voice).lower().startswith("m"):
        raise RuntimeError(
            "The male voice needs the neural voice engine: pip install edge-tts, and check the "
            f"internet connection. ({last or 'edge-tts not installed'}) gTTS only has a female voice."
        )
    try:
        from gtts import gTTS

        with _tts_lock:
            _tts_stats["fallbacks"] += 1
        gTTS(text=text, lang=LANG_CODES[language.lower()], slow=False).save(str(out))
    except Exception as exc:
        raise RuntimeError(f"Could not create the voice (needs internet): {exc}") from exc
    return str(out)


# ==================================================
# 6. PHOTOS
# ==================================================
_BAD_TITLE = ("logo", "icon", "flag of", "signature", "coat of arms", "stamp", "banner", "map of", "disambiguation")
_used_lock = threading.Lock()


def _words(q):
    return [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in _STOP]


def _get(url, timeout=6, headers=None):
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def _s_pexels(q, portrait):
    if not PEXELS_API_KEY:
        return []
    qs = urllib.parse.urlencode({"query": q, "per_page": 6, "orientation": "portrait" if portrait else "landscape"})
    d = json.loads(_get("https://api.pexels.com/v1/search?" + qs, headers={"Authorization": PEXELS_API_KEY}))
    return [(p["src"].get("large") or p["src"].get("medium"), "Pexels") for p in d.get("photos", []) if p.get("src")]


def _s_pixabay(q, portrait):
    if not PIXABAY_API_KEY:
        return []
    qs = urllib.parse.urlencode(
        {"key": PIXABAY_API_KEY, "q": q, "image_type": "photo", "per_page": 8, "safesearch": "true", "min_width": MIN_PHOTO_W}
    )
    d = json.loads(_get("https://pixabay.com/api/?" + qs))
    return [(h.get("largeImageURL") or h.get("webformatURL"), "Pixabay") for h in d.get("hits", [])]


def _s_wikipedia(q, portrait):
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": q,
            "gsrlimit": 6,
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 1280,
            "format": "json",
        }
    )
    d = json.loads(_get("https://en.wikipedia.org/w/api.php?" + qs))
    pages = sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        th, low = p.get("thumbnail") or {}, p.get("title", "").lower()
        if th.get("source") and th.get("width", 0) >= MIN_PHOTO_W and not any(b in low for b in _BAD_TITLE):
            out.append((th["source"], "Wikipedia"))
    return out[:3]


def _s_commons(q, portrait):
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {q}",
            "gsrnamespace": 6,
            "gsrlimit": 10,
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "iiurlwidth": 1280,
            "format": "json",
        }
    )
    d = json.loads(_get("https://commons.wikimedia.org/w/api.php?" + qs))
    pages = sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    words, out = _words(q), []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        title = p.get("title", "").lower()
        if info.get("mime") not in ("image/jpeg", "image/png") or any(b in title for b in _BAD_TITLE):
            continue
        if (info.get("thumbwidth") or 0) < MIN_PHOTO_W:
            continue
        if words and not any(w in title for w in words):
            continue
        out.append((info.get("thumburl") or info.get("url"), "Wikimedia Commons"))
    return out[:3]


def _download(url, out_path):
    raw = _get(url, timeout=8)
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        if im.width < MIN_PHOTO_W or im.height < MIN_PHOTO_H:
            return False
        if max(im.size) > 1600:
            im.thumbnail((1600, 1600), Image.LANCZOS)
        im.save(out_path, "JPEG", quality=92)
    return True


def find_photo(queries, out_path, portrait, budget=PHOTO_BUDGET, used=None):
    used = used if used is not None else set()
    deadline = time.time() + budget
    for q in dict.fromkeys(x.strip() for x in queries if x and x.strip()):
        for search in (_s_pexels, _s_pixabay, _s_wikipedia, _s_commons):
            if time.time() > deadline:
                return None
            try:
                for url, source in search(q, portrait):
                    if time.time() > deadline:
                        return None
                    with _used_lock:
                        if url in used:
                            continue
                    try:
                        if _download(url, out_path):
                            with _used_lock:
                                used.add(url)
                            return source
                    except Exception:
                        continue
            except Exception as exc:
                logger.debug("photo source %s failed: %s", search.__name__, exc)
    return None


# ==================================================
# 7. FFMPEG & AUDIO DURATION
# ==================================================
def get_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"):
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("FFmpeg was not found. Install it and add it to PATH.")


def get_ffprobe():
    found = shutil.which("ffprobe")
    if found:
        return found
    for p in (r"C:\ffmpeg\bin\ffprobe.exe", r"C:\Program Files\ffmpeg\bin\ffprobe.exe"):
        if os.path.isfile(p):
            return p
    return None


def get_audio_duration(audio_path):
    ffprobe = get_ffprobe()
    if ffprobe:
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            val = float(r.stdout.strip())
            if val > 0:
                return val
        except Exception:
            pass
    return 8.0


def run_ffmpeg(cmd, label):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg {label} failed: {r.stderr[-1500:]}")


# ==================================================
# 8. FRAME RENDERING  (glowing blue "AI lesson" look, NO pointer arrows)
# ==================================================
THEMES = {
    "school": dict(top=(4, 16, 64), bottom=(8, 84, 214), accent=(250, 204, 21), glow=(56, 189, 248), beam=(30, 110, 230), pill=(37, 99, 235)),
    "college": dict(top=(16, 8, 56), bottom=(78, 34, 150), accent=(251, 191, 36), glow=(167, 139, 250), beam=(110, 70, 220), pill=(109, 40, 217)),
    "teachers": dict(top=(12, 24, 34), bottom=(38, 84, 100), accent=(214, 174, 92), glow=(94, 234, 212), beam=(60, 150, 150), pill=(21, 128, 140)),
}
AUDIENCE_THEME = {"Kids": "school", "School Students": "school", "College Students": "college", "Teachers": "teachers"}
CYAN = (34, 211, 238)
NAVY = (8, 16, 48)

PRE_WORD = {"kannada": "ಪರಿಚಯ", "hindi": "परिचय"}
EXPLORE_WORD = {"english": "Let's Explore!", "kannada": "ಕಲಿಯೋಣ!", "hindi": "चलो सीखें!"}
_QUESTION_START = ("how", "what", "why", "when", "where", "explain", "describe", "who", "which", "can", "is", "are", "do", "does")

_FONT_FILES = {
    "latin": {
        False: ["arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"],
        True: ["arialbd.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"],
    },
    "kannada": {
        False: ["Nirmala.ttf", "NotoSansKannada-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansKannada-Regular.ttf", "/System/Library/Fonts/Supplemental/Kannada Sangam MN.ttc"],
        True: ["NirmalaB.ttf", "NotoSansKannada-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf",
               "/usr/share/fonts/opentype/noto/NotoSansKannada-Bold.ttf", "/System/Library/Fonts/Supplemental/Kannada Sangam MN.ttc"],
    },
    "hindi": {
        False: ["Nirmala.ttf", "NotoSansDevanagari-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf", "/System/Library/Fonts/Supplemental/DevanagariSangamMN.ttc"],
        True: ["NirmalaB.ttf", "NotoSansDevanagari-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
               "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf", "/System/Library/Fonts/Supplemental/DevanagariSangamMN.ttc"],
    },
}


@lru_cache(maxsize=256)
def _load_font(size, bold=False, script="latin"):
    size = max(8, int(size))
    names = list(_FONT_FILES.get(script, {}).get(bool(bold), [])) + _FONT_FILES["latin"][bool(bold)]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _metrics(font):
    try:
        return font.getmetrics()
    except Exception:
        return (12, 4)


def _tw(font, text):
    try:
        return font.getlength(text)
    except Exception:
        return len(text) * 8


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _wrap_px(text, font, max_w):
    lines, cur = [], ""
    for w in str(text or "").split():
        trial = (cur + " " + w).strip()
        if cur and _tw(font, trial) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _fit_font(text, max_w, size, bold=True, script="latin", min_size=12):
    s = int(size)
    while s > min_size:
        f = _load_font(s, bold, script)
        if _tw(f, text) <= max_w:
            return f
        s -= 2
    return _load_font(min_size, bold, script)


def _ellipsize(text, font, max_w):
    text = str(text or "")
    while len(text) > 1 and _tw(font, text) > max_w:
        text = text[:-2].rstrip() + "…" if not text.endswith("…") else text[:-2] + "…"
    return text


def _text_cy(draw, x, cy, text, font, fill, **kw):
    asc, desc = _metrics(font)
    draw.text((x, cy - (asc + desc) / 2), text, font=font, fill=fill, **kw)


@lru_cache(maxsize=12)
def _background(width, height, theme_key):
    th = THEMES[theme_key]
    img = Image.new("RGB", (width, height))
    d = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        d.line([(0, y), (width, y)], fill=_mix(th["top"], th["bottom"], t))
    beams = Image.new("RGB", (width, height), (0, 0, 0))
    bd = ImageDraw.Draw(beams)
    for fx, fw, fh in ((0.05, 0.020, 0.50), (0.12, 0.012, 0.35), (0.88, 0.014, 0.40), (0.95, 0.022, 0.55)):
        x = int(width * fx)
        bw = max(4, int(width * fw))
        bd.rectangle([x, 0, x + bw, int(height * fh)], fill=tuple(int(c * 0.55) for c in th["beam"]))
    beams = beams.filter(ImageFilter.GaussianBlur(max(3, width * 0.006)))
    return ImageChops.add(img, beams)


def _draw_orbs(img, t, th, width, height):
    d = ImageDraw.Draw(img)
    for i in range(8):
        x = int(width * (((i * 0.173 + 0.07) % 1.0) + 0.012 * math.sin(t * 0.9 + i)))
        y = int(height * ((i * 0.37 + t * 0.035) % 1.0))
        r = max(3, int(width * (0.005 + 0.002 * (i % 3))))
        d.ellipse([x - r * 3, y - r * 3, x + r * 3, y + r * 3], fill=_mix(th["bottom"], th["glow"], 0.18))
        d.ellipse([x - r * 2, y - r * 2, x + r * 2, y + r * 2], fill=_mix(th["bottom"], th["glow"], 0.45))
        d.ellipse([x - r, y - r, x + r, y + r], fill=_mix(th["glow"], (255, 255, 255), 0.8))


def _glow_text(base, xy, text, font, fill, glow, radius=8, stroke=0, stroke_fill=(4, 14, 50)):
    x, y = int(xy[0]), int(xy[1])
    pad = 2 * radius + 4
    asc, desc = _metrics(font)
    mask = Image.new("L", (int(_tw(font, text)) + 2 * pad + 8, asc + desc + 2 * pad + 8), 0)
    ImageDraw.Draw(mask).text((pad, pad), text, font=font, fill=255, stroke_width=stroke)
    mask = mask.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * 1.7)))
    base.paste(Image.new("RGB", mask.size, glow), (x - pad, y - pad), mask)
    ImageDraw.Draw(base).text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)


def _draw_robot(base, cx, cy, s, t=0.0, talking=False, body=False):
    """Original friendly robot teacher (white head, glowing cyan eyes, smile)."""
    d = ImageDraw.Draw(base)
    cy = cy + math.sin(t * 3.0) * s * 0.04
    lw = max(2, int(s * 0.03))
    hw, hh = s, s * 0.82
    shell, edge = (232, 236, 255), (150, 165, 232)
    if body:
        bw, bh = s * 0.78, s * 0.72
        bx0, by0 = cx - bw / 2, cy + hh / 2 - s * 0.06
        for sx in (-1, 1):  # arms
            ax = cx + sx * (bw / 2 + s * 0.04)
            d.ellipse([ax - s * 0.12, by0 + bh * 0.10, ax + s * 0.12, by0 + bh * 0.10 + s * 0.38], fill=(205, 214, 246), outline=edge, width=lw)
        d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + bh], radius=s * 0.22, fill=(214, 222, 250), outline=edge, width=lw)
        pw, ph = bw * 0.52, bh * 0.44
        px0, py0 = cx - pw / 2, by0 + bh * 0.2
        d.rounded_rectangle([px0, py0, px0 + pw, py0 + ph], radius=s * 0.07, fill=(10, 52, 128), outline=CYAN, width=lw)
        f = _load_font(int(ph * 0.62), True)
        d.text((cx - _tw(f, "AI") / 2, py0 + ph / 2 - sum(_metrics(f)) / 2), "AI", font=f, fill=CYAN)
    # antenna
    ox, oy = cx + s * 0.08, cy - hh / 2 - s * 0.22
    d.line([cx, cy - hh / 2, ox, oy], fill=(190, 200, 240), width=lw)
    r = s * 0.06
    d.ellipse([ox - r, oy - r, ox + r, oy + r], fill=(90, 220, 255), outline=(255, 255, 255))
    # ear pieces
    for sx in (-1, 1):
        ex = cx + sx * hw / 2
        d.ellipse([ex - s * 0.09, cy - s * 0.12, ex + s * 0.09, cy + s * 0.16], fill=(170, 185, 240), outline=(120, 140, 215), width=lw)
    # head + visor
    d.rounded_rectangle([cx - hw / 2, cy - hh / 2, cx + hw / 2, cy + hh / 2], radius=s * 0.3, fill=shell, outline=edge, width=lw)
    vw, vh = hw * 0.82, hh * 0.62
    d.rounded_rectangle([cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2], radius=s * 0.2, fill=NAVY)
    ey = cy - vh * 0.08
    blink = (t % 3.2) < 0.14
    for sx in (-1, 1):
        ex = cx + sx * vw * 0.26
        if blink:
            d.line([ex - s * 0.075, ey, ex + s * 0.075, ey], fill=CYAN, width=lw)
        else:
            d.ellipse([ex - s * 0.075, ey - s * 0.1, ex + s * 0.075, ey + s * 0.1], fill=CYAN)
            d.ellipse([ex - s * 0.03, ey - s * 0.06, ex + s * 0.02, ey - s * 0.01], fill=(220, 250, 255))
    my, mw = cy + vh * 0.2, s * 0.1
    if talking and int(t * 6) % 2 == 0:
        d.ellipse([cx - mw * 0.55, my - mw * 0.2, cx + mw * 0.55, my + mw * 0.7], fill=CYAN)
    else:
        d.arc([cx - mw, my - mw * 0.6, cx + mw, my + mw * 0.6], start=20, end=160, fill=CYAN, width=lw)


def _layout(width, height):
    m = int(width * 0.035)
    if height <= width:  # landscape 16:9
        pic = (m + 6, int(height * 0.19), int(width * 0.62), int(height * 0.72))
        return {
            "title": (m, int(height * 0.04), width - m, int(height * 0.15)),
            "pic": pic,
            "pills": (pic[2] + int(width * 0.035), pic[1], width - m, pic[3]),
            "cap": (m, int(height * 0.76), width - m, int(height * 0.93)),
        }
    return {  # portrait 9:16
        "title": (m, int(height * 0.03), width - m, int(height * 0.095)),
        "pic": (m + 6, int(height * 0.12), width - m - 6, int(height * 0.41)),
        "pills": (m, int(height * 0.44), width - m, int(height * 0.71)),
        "cap": (m, int(height * 0.74), width - m, int(height * 0.93)),
    }


def _caption_chunks(text, font, max_w, max_lines=2):
    """Split narration into 2-line caption pages with relative timing weights."""
    words, chunks, cur = str(text or "").split(), [], []
    for w in words:
        trial = cur + [w]
        if cur and len(_wrap_px(" ".join(trial), font, max_w)) > max_lines:
            chunks.append(" ".join(cur))
            cur = [w]
        else:
            cur = trial
    if cur:
        chunks.append(" ".join(cur))
    total = float(sum(len(c) + 1 for c in chunks)) or 1.0
    out, acc = [], 0.0
    for c in chunks:
        acc += (len(c) + 1) / total
        out.append((acc, c))
    return out


class SceneRenderer:
    """Builds the static parts of a scene once, then renders animated frames quickly."""

    def __init__(self, photo_path, title, key_term, labels, narration, width, height,
                 audience_tag, theme_key, scene_no, total, script="latin", photo_credit="",
                 captions=True, show_term=True, key_term_overlay=True):
        self.captions = bool(captions)
        self.show_term = bool(show_term)
        self.w, self.h = width, height
        self.theme_key = theme_key
        self.th = THEMES[theme_key]
        self.script = script
        self.labels = [str(x) for x in (labels or [])] or [str(title)]
        self.L = _layout(width, height)
        self.portrait = height > width
        cap = self.L["cap"]
        self.cap_font = _load_font(max(18, int(height * (0.03 if not self.portrait else 0.026))), False, script)
        self.chunks = _caption_chunks(narration, self.cap_font, (cap[2] - cap[0]) - int(width * 0.04))
        self.head_s = (self.L["title"][3] - self.L["title"][1]) * 0.78
        self.panel = self._build_panel(photo_path, title, key_term, audience_tag, scene_no, total, photo_credit)

    # ---------- static panel (title bar, picture card, caption box) ----------
    def _build_panel(self, photo_path, title, key_term, audience_tag, scene_no, total, credit):
        w, h, th, L, script = self.w, self.h, self.th, self.L, self.script
        x0, y0, x1, y1 = L["pic"]
        glow_mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(glow_mask).rounded_rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], radius=26, fill=210)
        panel = Image.new("RGBA", (w, h), th["glow"] + (0,))
        panel.putalpha(glow_mask.filter(ImageFilter.GaussianBlur(14)))
        d = ImageDraw.Draw(panel)

        # picture card
        d.rounded_rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], radius=24, fill=(8, 18, 52, 255), outline=th["glow"] + (255,), width=4)
        pw, ph = x1 - x0, y1 - y0
        has_photo = False
        if photo_path and os.path.exists(str(photo_path)):
            try:
                with Image.open(photo_path) as im:
                    photo = ImageOps.fit(im.convert("RGB"), (pw, ph), Image.LANCZOS)
                mask = Image.new("L", (pw, ph), 0)
                ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=18, fill=255)
                panel.paste(photo.convert("RGBA"), (x0, y0), mask)
                has_photo = True
            except Exception:
                logger.debug("photo paste failed", exc_info=True)
        if has_photo and credit:
            cf = _load_font(max(12, int(h * 0.02)), False, "latin")
            txt = f"Image: {str(credit)[:28]}"
            bw = int(_tw(cf, txt)) + 20
            ch = int(h * 0.04)
            d.rounded_rectangle([x0 + 12, y1 - ch - 12, x0 + 12 + bw, y1 - 12], radius=ch // 2, fill=(6, 14, 44, 215))
            _text_cy(d, x0 + 22, y1 - 12 - ch / 2, txt, cf, (226, 232, 240, 255))
        if not has_photo:
            self._key_card(d, key_term, title)
        elif self.show_term:
            self._term_pill(d, key_term)

        # title bar
        tx0, ty0, tx1, ty1 = L["title"]
        tbh = ty1 - ty0
        d.rounded_rectangle([tx0, ty0, tx1, ty1], radius=tbh // 2, fill=(6, 14, 44, 245), outline=th["glow"] + (255,), width=2)
        badge_txt = f"{audience_tag}  ·  {scene_no}/{total}" if (audience_tag and not self.portrait) else f"{scene_no}/{total}"
        bf = _load_font(max(13, int(tbh * 0.34)), True, "latin")
        bw = int(_tw(bf, badge_txt)) + 34
        bx1 = tx1 - 14
        bx0 = bx1 - bw
        d.rounded_rectangle([bx0, ty0 + tbh * 0.2, bx1, ty1 - tbh * 0.2], radius=tbh // 3, fill=th["accent"] + (255,))
        _text_cy(d, bx0 + 17, (ty0 + ty1) / 2, badge_txt, bf, (15, 23, 42, 255))
        title_x = tx0 + int(self.head_s * 1.65)
        tf = _fit_font(str(title), bx0 - title_x - 18, int(tbh * 0.5), True, script, 14)
        _text_cy(d, title_x, (ty0 + ty1) / 2, _ellipsize(str(title), tf, bx0 - title_x - 18), tf, (255, 255, 255, 255))

        # caption box
        if self.captions:
            cx0, cy0, cx1, cy1 = L["cap"]
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=18, fill=(244, 248, 255, 240), outline=th["glow"] + (255,), width=3)
        return panel

    def _term_pill(self, d, key_term):
        """Small 'Term: definition' label on top of the picture (the Key terms switch)."""
        kt = key_term if isinstance(key_term, dict) else {}
        term, definition = (kt.get("term") or "").strip(), (kt.get("definition") or "").strip()
        if not term:
            return
        x0, y0, x1, y1 = self.L["pic"]
        size = max(13, int(self.h * 0.024))
        bf, rf = _load_font(size, True, self.script), _load_font(size, False, self.script)
        max_w = (x1 - x0) - 48
        head = term + ": "
        room = max_w - int(_tw(bf, head)) - 8
        rest = _ellipsize(definition, rf, room) if (definition and room > 40) else ""
        width = int(_tw(bf, head if rest else term)) + (int(_tw(rf, rest)) if rest else 0) + 28
        ch = int(size * 2.1)
        d.rounded_rectangle([x0 + 12, y0 + 12, x0 + 12 + width, y0 + 12 + ch], radius=ch // 2, fill=(6, 14, 44, 228), outline=self.th["accent"] + (255,), width=2)
        _text_cy(d, x0 + 26, y0 + 12 + ch / 2, head if rest else term, bf, self.th["accent"] + (255,))
        if rest:
            _text_cy(d, x0 + 26 + _tw(bf, head), y0 + 12 + ch / 2, rest, rf, (255, 255, 255, 255))

    def _key_card(self, d, key_term, title):
        th, script = self.th, self.script
        x0, y0, x1, y1 = self.L["pic"]
        kt = key_term if isinstance(key_term, dict) else {}
        term = (kt.get("term") or str(title)).strip()
        definition = (kt.get("definition") or "").strip()
        pad = int((x1 - x0) * 0.06)
        tag_f = _load_font(max(14, int(self.h * 0.026)), True, "latin")
        d.rounded_rectangle([x0 + pad, y0 + pad, x0 + pad + int(_tw(tag_f, "KEY IDEA")) + 28, y0 + pad + int(self.h * 0.05)],
                            radius=18, fill=th["accent"] + (255,))
        _text_cy(d, x0 + pad + 14, y0 + pad + self.h * 0.025, "KEY IDEA", tag_f, (15, 23, 42, 255))
        tf = _fit_font(term, x1 - x0 - 2 * pad, int(self.h * 0.085), True, script, 20)
        ty = y0 + pad + int(self.h * 0.09)
        d.text((x0 + pad, ty), term, font=tf, fill=th["accent"] + (255,))
        df = _load_font(max(16, int(self.h * 0.03)), False, script)
        yy = ty + sum(_metrics(tf)) + int(self.h * 0.025)
        for line in _wrap_px(definition, df, x1 - x0 - 2 * pad)[:5]:
            if yy + sum(_metrics(df)) > y1 - pad:
                break
            d.text((x0 + pad, yy), line, font=df, fill=(226, 238, 255, 255))
            yy += int(sum(_metrics(df)) * 1.25)

    # ---------- dynamic parts ----------
    def _pills(self, base, t, active):
        d = ImageDraw.Draw(base)
        th, script = self.th, self.script
        px0, py0, px1, py1 = self.L["pills"]
        n = len(self.labels)
        step = min(int(self.h * 0.105), (py1 - py0) / max(1, n))
        ph = int(step * 0.8)
        pf_size = max(14, int(ph * 0.42))
        for i, label in enumerate(self.labels):
            y = py0 + int(i * step)
            if i == active:
                fill, outline, tcol = th["accent"], (255, 255, 255), (15, 23, 42)
                cfill, cnum = NAVY, th["accent"]
                x0 = px0 - int(4 + 4 * math.sin(t * 5))
            elif i < active:
                fill, outline, tcol = th["pill"], th["glow"], (255, 255, 255)
                cfill, cnum = (255, 255, 255), th["pill"]
                x0 = px0
            else:
                fill, outline, tcol = _mix(th["top"], th["bottom"], 0.15), _mix(th["glow"], th["top"], 0.55), _mix((200, 215, 245), th["top"], 0.25)
                cfill, cnum = _mix(th["glow"], th["top"], 0.55), (255, 255, 255)
                x0 = px0
            d.rounded_rectangle([x0, y, px1, y + ph], radius=ph // 2, fill=fill, outline=outline, width=2)
            cd = ph - 14
            d.ellipse([x0 + 7, y + 7, x0 + 7 + cd, y + 7 + cd], fill=cfill)
            nf = _load_font(max(12, int(cd * 0.55)), True, "latin")
            ntxt = str(i + 1)
            d.text((x0 + 7 + cd / 2 - _tw(nf, ntxt) / 2, y + ph / 2 - sum(_metrics(nf)) / 2), ntxt, font=nf, fill=cnum)
            tx = x0 + ph + 4
            lf = _fit_font(label, px1 - tx - 16, pf_size, True, script, 11)
            _text_cy(d, tx, y + ph / 2, _ellipsize(label, lf, px1 - tx - 16), lf, tcol)

    def _caption(self, base, ratio):
        if not self.captions:
            return
        d = ImageDraw.Draw(base)
        cx0, cy0, cx1, cy1 = self.L["cap"]
        text = ""
        for bound, chunk in self.chunks:
            text = chunk
            if ratio <= bound:
                break
        lines = _wrap_px(text, self.cap_font, (cx1 - cx0) - int(self.w * 0.04))[:2]
        lh = int(sum(_metrics(self.cap_font)) * 1.2)
        y = (cy0 + cy1) / 2 - lh * len(lines) / 2
        for line in lines:
            lw = _tw(self.cap_font, line)
            d.text(((cx0 + cx1) / 2 - lw / 2, y), line, font=self.cap_font, fill=(15, 23, 42))
            y += lh

    def frame(self, t, ratio, progress):
        base = _background(self.w, self.h, self.theme_key).copy()
        _draw_orbs(base, t, self.th, self.w, self.h)
        base.paste(self.panel, (0, 0), self.panel)
        self._pills(base, t, min(len(self.labels) - 1, int(ratio * len(self.labels))))
        self._caption(base, ratio)
        tx0, ty0, tx1, ty1 = self.L["title"]
        _draw_robot(base, tx0 + self.head_s * 0.85, (ty0 + ty1) / 2 + self.head_s * 0.06, self.head_s, t, talking=True)
        d = ImageDraw.Draw(base)
        bx0, bx1, by = self.L["cap"][0], self.L["cap"][2], self.h - max(10, int(self.h * 0.03))
        d.rounded_rectangle([bx0, by, bx1, by + 7], radius=4, fill=_mix(self.th["top"], self.th["bottom"], 0.4))
        fw = int((bx1 - bx0) * max(0.0, min(1.0, progress)))
        if fw > 8:
            d.rounded_rectangle([bx0, by, bx0 + fw, by + 7], radius=4, fill=self.th["accent"])
        if t < 0.3:
            base = Image.blend(Image.new("RGB", base.size, self.th["top"]), base, t / 0.3)
        return base


def draw_intro_frame(title, language, t, width, height, theme_key="school", audience_tag="School Level"):
    """Animated title card: white lead-in line, glowing yellow title, robot waving in."""
    th = THEMES[theme_key]
    lang = language.lower()
    script = lang if lang in SCRIPT_RANGES else "latin"
    w, h = width, height
    portrait = h > w
    base = _background(w, h, theme_key).copy()
    _draw_orbs(base, t, th, w, h)
    d = ImageDraw.Draw(base)

    title = str(title or "").strip() or "Lesson"
    if lang == "english":
        first = title.split()[0].lower().strip("?,.") if title.split() else ""
        pre = "Let's Learn" if (first in _QUESTION_START or len(title.split()) > 6) else "Introduction to"
    else:
        pre = PRE_WORD.get(lang, "")
    explore = EXPLORE_WORD.get(lang, EXPLORE_WORD["english"])

    if portrait:
        ax0, ay0, ax1, ay1 = int(w * 0.07), int(h * 0.12), int(w * 0.93), int(h * 0.50)
        robot = (w * 0.5, h * 0.68, w * 0.46)
    else:
        ax0, ay0, ax1, ay1 = int(w * 0.06), int(h * 0.12), int(w * 0.60), int(h * 0.80)
        robot = (w * 0.81, h * 0.40, h * 0.46)
    max_w = ax1 - ax0

    pre_f = _fit_font(pre or " ", max_w, int(h * (0.075 if not portrait else 0.045)), True, script, 16)
    size = int(h * (0.12 if not portrait else 0.07))
    while True:
        tf = _load_font(size, True, script)
        lines = _wrap_px(title, tf, max_w)
        if (len(lines) <= 3 and all(_tw(tf, ln) <= max_w for ln in lines)) or size <= 24:
            break
        size -= 4
    line_h = int(sum(_metrics(tf)) * 1.08)
    pre_h = int(sum(_metrics(pre_f)) * 1.15) if pre else 0
    exp_f = _load_font(max(16, int(h * (0.04 if not portrait else 0.028))), True, script)
    exp_h = int(h * 0.075)
    block_h = pre_h + len(lines) * line_h + int(h * 0.04) + exp_h
    y = ay0 + max(0, ((ay1 - ay0) - block_h) // 2)

    e1 = _ease(t / 0.7)
    e2 = _ease((t - 0.25) / 0.7)
    e3 = _ease((t - 1.0) / 0.6)

    def xpos(width_px):
        return ax0 if not portrait else (ax0 + ax1) / 2 - width_px / 2

    if pre:
        _glow_text(base, (xpos(_tw(pre_f, pre)) - (1 - e1) * w * 0.25, y), pre, pre_f, (255, 255, 255), th["glow"], radius=6, stroke=max(1, pre_f.size // 22 if hasattr(pre_f, "size") else 2))
    y += pre_h
    longest = 0
    for ln in lines:
        lwid = _tw(tf, ln)
        longest = max(longest, lwid)
        _glow_text(base, (xpos(lwid) + (1 - e2) * w * 0.25, y), ln, tf, th["accent"], th["accent"], radius=max(6, size // 9), stroke=max(2, size // 22))
        y += line_h
    # swoosh underline
    sw_w = int(longest * e2)
    sx = xpos(longest)
    d.rounded_rectangle([sx, y + 4, sx + sw_w, y + 4 + max(5, size // 11)], radius=6, fill=th["accent"])
    # sparks next to the title
    spark_x = sx + longest + 14 if not portrait else min(w - 40, sx + longest + 6)
    spark_y = y - len(lines) * line_h
    for k, (dx, dy) in enumerate(((10, 6), (22, -10), (4, -22))):
        grow = 0.6 + 0.4 * math.sin(t * 6 + k)
        if e2 > 0.5:
            d.line([spark_x + dx, spark_y + dy + 18, spark_x + dx + 12 * grow, spark_y + dy + 18 - 10 * grow], fill=th["accent"], width=max(3, int(h * 0.006)))
    # "Let's Explore!" pill
    ey0 = y + int(h * 0.04) + int((1 - e3) * 30)
    pw = int(_tw(exp_f, explore)) + int(h * 0.1)
    px0 = xpos(pw)
    if e3 > 0.02:
        d.rounded_rectangle([px0, ey0, px0 + pw, ey0 + exp_h], radius=exp_h // 2, fill=th["pill"], outline=(255, 255, 255), width=2)
        _text_cy(d, px0 + (pw - _tw(exp_f, explore)) / 2, ey0 + exp_h / 2, explore, exp_f, (255, 255, 255))

    # robot slides in
    rcx, rcy, rs = robot
    _draw_robot(base, rcx + (1 - _ease(t / 0.9)) * w * 0.3, rcy, rs, t, talking=False, body=True)

    # small brand tag
    bf = _load_font(max(13, int(h * 0.024)), True, "latin")
    tag = f"EduVision  ·  {audience_tag}" if audience_tag else "EduVision"
    bw = int(_tw(bf, tag)) + 30
    d.rounded_rectangle([int(w * 0.035), int(h * 0.035), int(w * 0.035) + bw, int(h * 0.035) + int(h * 0.055)], radius=20, fill=(6, 14, 44), outline=th["glow"], width=2)
    _text_cy(d, int(w * 0.035) + 15, int(h * 0.035) + h * 0.0275, tag, bf, (255, 255, 255))

    if t < 0.3:
        base = Image.blend(Image.new("RGB", base.size, th["top"]), base, t / 0.3)
    return base


def prepare_renderer(photo_path, sc, idx, total, width, height, audience_tag, theme_key, script, narration=None, credit="",
                     captions=True, show_term=True):
    return SceneRenderer(
        photo_path=photo_path,
        title=sc["title"],
        key_term=sc.get("key_term"),
        labels=sc.get("labels"),
        narration=narration or sc["narration"],
        width=width,
        height=height,
        audience_tag=audience_tag,
        theme_key=theme_key,
        scene_no=idx + 1,
        total=total,
        script=script,
        photo_credit=credit,
        captions=captions,
        show_term=show_term,
    )


# ==================================================
# 9. MAIN PACKAGE GENERATOR (Required by app.py)
# ==================================================
def _save_frames(frames_dir, total_frames, make_frame):
    """Render frames one by one, JPEG-encode them on worker threads."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    with ThreadPoolExecutor(max_workers=RENDER_WORKERS) as pool:
        for i in range(total_frames):
            img = make_frame(i)
            pending.append(pool.submit(img.save, str(frames_dir / f"frame_{i:05d}.jpg"), "JPEG", quality=90))
            if len(pending) >= RENDER_WORKERS * 3:
                pending.pop(0).result()
        for f in pending:
            f.result()


def _split_topic(source_text):
    """app.py sends the typed topic and any file text together as source_text."""
    text = str(source_text or "").strip()
    if not text:
        return "Educational Lesson", ""
    first = text.split("\n", 1)[0].strip()
    if len(text) <= 220 and "\n" not in text:
        return text, ""            # just a topic, no extra material
    if len(first) <= 220:
        return first, text         # first line = topic, everything = source material
    return first[:200].rsplit(" ", 1)[0], text


def _add_music(ffmpeg, src, dst, seconds):
    """Mix a very soft ambient pad under the lesson (video stream is copied, only audio is re-encoded)."""
    d = max(3.0, float(seconds))
    cmd = [ffmpeg, "-y", "-i", str(src)]
    for f in (220.0, 277.18, 329.63):
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={f}:sample_rate=44100:duration={d:.2f}"]
    cmd += [
        "-filter_complex",
        "[1:a][2:a][3:a]amix=inputs=3,volume=0.04,tremolo=f=0.25:d=0.5,aformat=channel_layouts=stereo,"
        f"afade=t=in:d=2,afade=t=out:st={max(0.0, d - 2):.2f}:d=2[m];"
        "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", str(dst),
    ]
    run_ffmpeg(cmd, "music")


def generate_video_package(
    topic="",
    source_text="",
    audience="",
    difficulty="",
    language="English",
    style="Educational",
    voice="Female",
    duration_minutes=None,
    aspect_ratio="16:9",
    progress=None,
    progress_callback=None,
    subtitles=True,
    highlights=True,
    music=False,
    image_path=None,
    duration="",
    include_intro=True,
    **kwargs,
):
    """
    Main entry point imported by app.py (called with progress=callback(percent, message)).
    Writes the lesson, records narration, fetches photos, renders the glowing-blue animated
    scenes (title intro + robot teacher + numbered point pills, NO arrows), encodes the MP4
    and returns what app.py saves: path/filename, duration_seconds, script_text and more.
    """
    callback = progress or progress_callback
    ffmpeg = get_ffmpeg()

    if topic and str(topic).strip():
        topic, source = str(topic).strip(), str(source_text or "").strip()
    else:
        topic, source = _split_topic(source_text or kwargs.get("title") or "")
    audience_given = bool(str(audience or "").strip())
    audience = pick(audience, AUDIENCES, "School Students")
    difficulty = pick(difficulty, LEVELS, DEFAULT_LEVEL.get(audience, "Beginner"))
    language = pick(language, list(LANG_KEYS.values()), "English")
    style = normalize_style(style)
    try:
        minutes = float(duration_minutes)
    except (TypeError, ValueError):
        minutes = float(DEFAULT_MINUTES)
    minutes = max(1.0, min(float(MAX_MINUTES), minutes))
    width, height = ASPECTS.get(aspect_ratio, (1280, 720))
    script = language.lower() if language.lower() in SCRIPT_RANGES else "latin"
    theme_key = AUDIENCE_THEME.get(audience, "school")
    audience_tag = AUDIENCE_TAG.get(audience, "School Level") if audience_given else ""

    def _report(pct, msg):
        # Only Exception is swallowed: app.py cancels a job by raising JobCancelled (a BaseException).
        if callable(callback):
            try:
                callback(int(max(0.0, min(0.99, pct)) * 100), msg)
            except Exception:
                logger.debug("progress callback failed", exc_info=True)

    _report(0.03, "Preparing lesson script...")
    video_title, scenes, engine_used = build_script(
        topic=topic,
        source=source,
        audience=audience,
        difficulty=difficulty,
        language=language,
        style=style,
        minutes=minutes,
        progress=lambda r, m: _report(0.05 + 0.25 * r, m),
    )

    job_id = uuid.uuid4().hex[:10]
    job_dir = TEMP_DIR / f"job_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    used_urls, credits, clips, clip_seconds = set(), [], [], 0.0
    rate_pct = VOICE_RATE.get(audience, 0)
    fallbacks_before = _tts_stats["fallbacks"]
    vcodec = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-crf", CRF, "-r", str(FPS)]
    acodec = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
    n_scenes = len(scenes)

    try:
        # ---- animated title intro (silent) ----
        if include_intro:
            _report(0.30, "Creating the title intro...")
            frames = job_dir / "frames_intro"
            _save_frames(
                frames, INTRO_SECONDS * FPS,
                lambda i: draw_intro_frame(video_title, language, i / FPS, width, height, theme_key, audience_tag),
            )
            clip = job_dir / "clip_intro.mp4"
            run_ffmpeg(
                [ffmpeg, "-y", "-framerate", str(FPS), "-i", str(frames / "frame_%05d.jpg"),
                 "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", *vcodec, *acodec,
                 "-t", str(INTRO_SECONDS), "-shortest", str(clip)],
                "intro",
            )
            clips.append(clip)
            clip_seconds += INTRO_SECONDS
            shutil.rmtree(frames, ignore_errors=True)

        # ---- lesson scenes ----
        for idx, sc in enumerate(scenes):
            _report(0.32 + 0.58 * (idx / max(1, n_scenes)), f"Creating scene {idx + 1} of {n_scenes}...")

            audio_file = job_dir / f"scene_{idx:02d}.mp3"
            generate_narration(sc["narration"], audio_file, language=language, voice=voice, rate_pct=rate_pct)
            dur = get_audio_duration(audio_file) + PAUSE

            photo_file = job_dir / f"photo_{idx:02d}.jpg"
            credit = None
            if idx == 0 and image_path and os.path.isfile(str(image_path)):
                try:  # the picture the user uploaded leads the first scene
                    with Image.open(image_path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((1600, 1600), Image.LANCZOS)
                        im.save(photo_file, "JPEG", quality=92)
                    credit = "Your image"
                except Exception:
                    logger.warning("Could not use the uploaded image", exc_info=True)
            if not credit:
                credit = find_photo(
                    [sc.get("image_query"), sc.get("image_query_alt"), topic],
                    photo_file, portrait=(height > width), used=used_urls,
                )
            if credit and credit not in credits:
                credits.append(credit)

            renderer = prepare_renderer(
                photo_file if credit and photo_file.exists() else None,
                sc, idx, n_scenes, width, height, audience_tag, theme_key, script,
                credit=credit or "", captions=bool(subtitles), show_term=bool(highlights),
            )
            total_frames = max(2, int(math.ceil(dur * FPS)))

            def make_frame(i, renderer=renderer, total_frames=total_frames, idx=idx):
                if i % 12 == 0:  # keeps the progress bar moving and lets Cancel work mid-scene
                    _report(0.32 + 0.58 * ((idx + i / total_frames) / max(1, n_scenes)),
                            f"Drawing scene {idx + 1} of {n_scenes}...")
                ratio = i / max(1, total_frames - 1)
                return renderer.frame(i / FPS, ratio, (idx + ratio) / max(1, n_scenes))

            frames = job_dir / f"frames_{idx:02d}"
            _save_frames(frames, total_frames, make_frame)

            clip = job_dir / f"clip_{idx:02d}.mp4"
            run_ffmpeg(
                [ffmpeg, "-y", "-framerate", str(FPS), "-i", str(frames / "frame_%05d.jpg"),
                 "-i", str(audio_file), *vcodec, *acodec,
                 "-af", f"apad=pad_dur={PAUSE}", "-shortest", str(clip)],
                f"scene_{idx}",
            )
            clips.append(clip)
            clip_seconds += total_frames / FPS
            shutil.rmtree(frames, ignore_errors=True)

        # ---- stitch (+ optional soft music) ----
        _report(0.92, "Putting the video together...")
        concat_list = job_dir / "concat.txt"
        concat_list.write_text("\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf-8")
        out_name = f"eduvision_{job_id}.mp4"
        out_path = GENERATED_DIR / out_name
        stitched = job_dir / "stitched.mp4" if music else out_path
        run_ffmpeg(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", "-movflags", "+faststart", str(stitched)],
            "concat",
        )
        if music:
            _report(0.96, "Adding soft music...")
            try:
                _add_music(ffmpeg, stitched, out_path, clip_seconds)
            except Exception:
                logger.warning("Soft music could not be added; keeping the video without it.", exc_info=True)
                shutil.copy(str(stitched), str(out_path))

        total_seconds = int(round(get_audio_duration(out_path))) if get_ffprobe() else int(round(clip_seconds))
        script_text = (video_title + "\n\n" if video_title else "") + "\n\n".join(
            f"{sc['title']}\n{sc['narration']}" for sc in scenes
        )
        _report(0.99, "Video ready!")
        return {
            "title": video_title,
            "path": str(out_path),
            "video_path": str(out_path),
            "video_url": f"/static/generated/{out_name}",
            "filename": out_name,
            "duration_seconds": total_seconds,
            "script_text": script_text,
            "scenes": scenes,
            "scene_count": n_scenes,
            "script_mode": "ai" if engine_used == "ai" else "algo",
            "engine": engine_used,
            "voice_engine": "gtts" if _tts_stats["fallbacks"] > fallbacks_before else "edge-tts",
            "credits": credits,
            "audience": audience,
            "difficulty": difficulty,
            "language": language,
            "style": style,
        }
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


# ==================================================
# VIDEO QUIZ GENERATION
# ==================================================
def generate_quiz(script, language="English", difficulty="Beginner", count=5):
    """
    Generate a source-grounded multiple-choice quiz for a lesson.

    Return format is consumed by routes/video_quiz.py:
    [
        {
            "question": "...",
            "options": ["...", "...", "...", "..."],
            "correct_index": 0,
            "explanation": "..."
        }
    ]
    """
    lesson = str(script or "").strip()
    if len(lesson) < 40:
        raise ValueError("The saved lesson text is too short to create a useful quiz.")

    try:
        question_count = max(3, min(10, int(count)))
    except (TypeError, ValueError):
        question_count = 5

    language = str(language or "English").strip()[:40]
    difficulty = str(difficulty or "Beginner").strip()[:40]
    # Keep the prompt within a reasonable size for local models.
    lesson_for_prompt = lesson[:14000]

    prompt = f"""
Create exactly {question_count} multiple-choice questions from the lesson below.
Language: {language}
Difficulty: {difficulty}

Rules:
- Questions must be answerable from the lesson. Do not add outside facts.
- Each question must have exactly four short, distinct options.
- There must be exactly one correct option.
- correct_index must be an integer: 0, 1, 2, or 3.
- explanation must briefly explain why the correct option is right.
- Avoid duplicate questions and avoid "all of the above".
- Return valid JSON only, in this exact structure:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 0,
      "explanation": "Short explanation"
    }}
  ]
}}

LESSON:
{lesson_for_prompt}
"""
    data = ask_json(prompt)
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list):
        raise ValueError("The AI response did not contain a questions list.")

    cleaned = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        options = item.get("options")
        explanation = str(item.get("explanation") or "").strip()
        try:
            correct_index = int(item.get("correct_index"))
        except (TypeError, ValueError):
            continue

        if (
            not question
            or not isinstance(options, list)
            or len(options) != 4
            or correct_index not in range(4)
        ):
            continue

        options = [str(option).strip() for option in options]
        if any(not option for option in options) or len(set(options)) != 4:
            continue

        cleaned.append({
            "question": question,
            "options": options,
            "correct_index": correct_index,
            "explanation": explanation or "Review the lesson to understand this answer.",
        })
        if len(cleaned) == question_count:
            break

    if len(cleaned) < 3:
        raise ValueError(
            "The AI returned too few valid quiz questions. Please try generating the quiz again."
        )
    return cleaned
