"""
video_generator.py  --  EduVision video generator (generator + optional Flask web part)

SAVE THIS FILE AS:  services/video_generator.py   (and keep an empty services/__init__.py)
ALSO SAVE:          services/indic_text.py        (draws Kannada / Hindi letters correctly, no RAQM needed)
                    services/ai_images.py         (optional AI pictures)

Topic (or pasted text / PDF / TXT / PICTURE)  ->  script  ->  male / female voice  ->  relevant visuals  ->  animated MP4  ->  quiz

WHAT CHANGED IN THIS VERSION
    * KANNADA / HINDI WORK WITHOUT PILLOW'S RAQM ENGINE. Text is shaped with HarfBuzz (pip install uharfbuzz),
      see services/indic_text.py. If RAQM happens to be available, Pillow is used as before.
    * NO girl / boy / teacher / mascot on the video any more. The picture area is bigger and clean.
      Only the small AI robot stays in the corner.
    * RELEVANT VISUALS ONLY. Every scene is marked by the AI as "photo" (a real physical thing: heart, volcano,
      engine ...) or "diagram" (software, maths, processes, abstract ideas). Abstract scenes are NEVER given a random
      stock photo. Photos are also checked against the photo's own title / tags and rejected if they do not match.
      Diagram scenes are drawn as a clean concept card (key term + definition).
    * REAL EXAMPLE IN EVERY LESSON SCENE. Each scene has a "Real example" box: GIVEN -> RESULT with real values,
      for example   I love cats  ->  I | love | cats.   The narration ends with "For example ..." and says the same thing.
    * The web page shows ONLY an error message when something cannot start or fails.

PICTURE RULE:
    * Only EDUCATIONAL pictures make a video (diagram, labelled figure, chart, map, textbook / notes page,
      science / maths / history picture). Anything else is refused with:
      "I can't read this file. Please upload an educational image ..."   No video is made, no credits are used.
    * app.py calls check_educational_image() BEFORE charging credits.
    * Phone numbers, e-mail addresses and links are removed from resumes and are never spoken.

app.py imports from this file:
    extract_text, generate_video_package, ai_status, check_educational_image, NOT_EDUCATIONAL_MSG,
    UI_MAX_MINUTES, DEFAULT_MINUTES, USE_ALGOS, SCRIPT_MODE

generate_video_package() returns a dict that ALWAYS contains "path" and "filename".

COMMAND LINE (no web page)
    python video_generator.py "Photosynthesis" --audience "School Students" --level Beginner --minutes 2 --voice Male
    python video_generator.py "ಪ್ರಕಾಶ ಸಂಶ್ಲೇಷಣೆ" --language Kannada --minutes 2
    python video_generator.py --image heart.png --minutes 2

INSTALL
    pip install pillow edge-tts gTTS python-dotenv flask
    pip install uharfbuzz         (Kannada / Hindi letters, no extra DLL needed)
    pip install deep-translator   (Kannada/Hindi when no AI model is available)
    pip install PyMuPDF           (PDF upload)
    pip install pytesseract       (optional: read text from pictures when no vision AI is available)
    FFmpeg must be on PATH.

.env (all optional)
    GEMINI_API_KEY  GEMINI_MODEL  OLLAMA_URL  OLLAMA_MODEL  OLLAMA_VISION_MODEL  PEXELS_API_KEY  PIXABAY_API_KEY
    QUICK_VIDEO_COST=10  UI_MAX_MINUTES=10  RENDER_WIDTH=1280  FPS=8  CRF=23  RENDER_WORKERS=3

IMPORTANT: after replacing this file, RESTART your Flask server. Videos you already made keep the old look.
"""
import asyncio
import base64
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:                                                  # AI pictures for scenes (services/ai_images.py), optional
    from services import ai_images
except ImportError:
    try:
        import ai_images
    except ImportError:
        ai_images = None

try:                                                  # Kannada / Hindi shaping without RAQM (services/indic_text.py)
    from services import indic_text
except ImportError:
    try:
        import indic_text
    except ImportError:
        indic_text = None

try:
    from dotenv import load_dotenv
except ImportError:                                   # python-dotenv is optional
    load_dotenv = None

logger = logging.getLogger("quick_video")

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
GEMINI_FALLBACKS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-2.5-flash-lite").split(",") if m.strip()]
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
USER_AGENT = "EduVision/1.0 (educational project)"

FPS = _env_int("FPS", 8, 4, 15)
CRF = str(_env_int("CRF", 23, 14, 32))
RENDER_WIDTH = _env_int("RENDER_WIDTH", 1280, 480, 1920)
RENDER_WORKERS = _env_int("RENDER_WORKERS", 3, 1, 8)
PHOTO_BUDGET = _env_int("PHOTO_BUDGET_SECONDS", 8, 3, 60)
MIN_PHOTO_W, MIN_PHOTO_H = 640, 360
MAX_MINUTES = _env_int("UI_MAX_MINUTES", 10, 1, 60)
PAUSE = 0.7                       # silence at the end of each scene
INTRO_SECONDS = 3
SECONDS_PER_SCENE = 25            # target length of one scene

# Values read by app.py
UI_MAX_MINUTES = MAX_MINUTES
DEFAULT_MINUTES = 3
USE_ALGOS = True
SCRIPT_MODE = "hybrid"

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280)}
WORDS_PER_MINUTE = {"english": 150, "kannada": 115, "hindi": 135}
LANG_KEYS = {"english": "English", "kannada": "Kannada", "hindi": "Hindi"}
SCRIPT_RANGES = {"kannada": (0x0C80, 0x0CFF), "hindi": (0x0900, 0x097F)}
LANG_CODES = {"english": "en", "kannada": "kn", "hindi": "hi"}
EXAMPLE_WORD = {"english": "Real example", "kannada": "ಉದಾಹರಣೆ", "hindi": "उदाहरण"}
LANGUAGE_NOTE = {
    "english": "Write everything in clear English.",
    "kannada": "Write everything in Kannada script (ಕನ್ನಡ). No English letters, no English answer. Natural spoken Kannada like a teacher.",
    "hindi": "Write everything in Hindi Devanagari script (देवनागरी). No Hinglish, no English answer. Simple spoken Hindi like a teacher.",
}

AUDIENCES = ["School Students", "College Students", "Teachers"]
LEVELS = ["Beginner", "Intermediate", "Advanced"]
AUDIENCE_TAG = {"School Students": "School Level", "College Students": "College Level", "Teachers": "Teachers Level"}
DEFAULT_LEVEL = {"School Students": "Beginner", "College Students": "Intermediate", "Teachers": "Advanced"}
LEVEL_LABELS = {"Beginner": 3, "Intermediate": 4, "Advanced": 5}          # on-screen point pills per scene
LEVEL_WORDS = {"Beginner": 0.9, "Intermediate": 1.0, "Advanced": 1.15}     # narration length factor

# The same topic must be taught differently for each audience x level.
TEACHING_RULES = {
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
    "Educational": "Calm professional teacher giving a lecture: define the key term, explain the steps in order, then a real-world example. Say what to look at on the screen.",
    "Storytelling": "ONE continuing story with two named characters. Each scene is one story beat in a concrete visible place that also explains the real concept. Happy ending that sums up the lesson.",
    "Simple Explanation": "Talk to a complete beginner. One idea per scene, one familiar comparison, every hard word explained at once.",
    "Presenter": "A friendly presenter speaking to the viewer: greeting in scene 1, natural spoken sentences, a one-sentence takeaway at the end.",
}

# ---- what KIND of content the input is (decided from the picture / text) ----
KINDS = ("educational", "general", "resume", "document")
_QUERY_RULE = ("image_query: only when visual is 'photo'. ENGLISH 2-5 words naming the REAL physical subject of this scene "
               "(for example 'human heart anatomy', 'volcano eruption'). NEVER the comparison or analogy "
               "(no 'lunch box', 'gears', 'clock'). When visual is 'diagram' leave it as an empty string.")
KIND_INFO = {
    "educational": dict(
        noun="classroom video",
        flow="hook + objectives -> basic concept -> step-by-step explanation (one idea per scene, each with a real "
             "worked example) -> demonstrations -> applications / common mistakes -> summary.",
        narr="about {words} words, spoken teacher voice, plain sentences for text-to-speech, no Markdown, no lists. "
             "Order: (1) a plain, clear definition or answer in simple words, (2) how or why it works, "
             "(3) the LAST sentence starts with 'For example' and says exactly the same example that is in the example field. "
             "Match the audience and level exactly.",
        query=_QUERY_RULE),
    "general": dict(
        noun="explainer video",
        flow="what it is -> its main parts or features -> how it works or what it is used for -> interesting facts -> summary.",
        narr="about {words} words, spoken teacher voice, plain sentences for text-to-speech, no Markdown, no lists. "
             "The FIRST sentence says plainly what it is. The LAST sentence starts with 'For example' and says exactly "
             "the same example that is in the example field. Match the audience and level exactly.",
        query=_QUERY_RULE),
    "resume": dict(
        noun="professional profile video",
        flow="introduction of the person -> education -> skills -> work experience / internships -> projects -> "
             "achievements and certifications -> career goal and closing.",
        narr="about {words} words, friendly professional presenter voice, plain sentences for text-to-speech, no Markdown, "
             "no lists. Use ONLY facts from the source material and skip anything it does not say. Never read out phone "
             "numbers, e-mail addresses, links or home addresses.",
        query="image_query: ENGLISH 2-5 words for ONE generic stock photograph that fits the section (for example "
              "'university campus students', 'software developer laptop', 'team meeting office'). Never a person's name. "
              "visual is always 'photo'.",
        rules="The SOURCE MATERIAL is a person's resume. Make a professional profile video that presents this person. "
              "Speak about them in the third person using their name (or 'they'). Use ONLY facts in the source; if a section "
              "is missing, skip it; never invent employers, dates, marks or numbers. Positive, confident, respectful tone."),
    "document": dict(
        noun="document explainer video",
        flow="what the document is and its purpose -> its main sections one by one -> the important details -> "
             "conclusion and action points.",
        narr="about {words} words, clear presenter voice, plain sentences for text-to-speech, no Markdown, no lists. "
             "Use ONLY facts from the source material. Never read out phone numbers, e-mail addresses or links.",
        query="image_query: ENGLISH 2-5 words for ONE generic stock photograph related to the document's subject. "
              "Never names. visual is always 'photo'.",
        rules="The SOURCE MATERIAL is a document (letter, report, notice, certificate, form or poster). Explain clearly what "
              "it is, who it is for and what its important points are. Use ONLY facts in the source; never invent details."),
}
KIND_LABEL = {"resume": "Professional Profile", "document": "Document Summary"}
KIND_CHIP = {"resume": "Career Profile", "document": "Quick Summary"}


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
# 2. AI TEXT (Gemini -> Ollama), always JSON.  Can also LOOK at one picture.
# ==================================================
_SYSTEM = ("You are an expert teacher and educational video director. Create accurate, engaging content "
           "for students. Never invent facts. Every example must be real, concrete and correct. "
           "Always return valid JSON only.")


def _post_json(url, payload, headers=None, timeout=60):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _image_b64(path, max_side=1600):
    """Picture file -> base64 JPEG (resized) for the vision models."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _gemini(prompt, image=None):
    if not GEMINI_API_KEY:
        raise RuntimeError("No GEMINI_API_KEY")
    last = None
    for model in [GEMINI_MODEL] + GEMINI_FALLBACKS:
        cfg = {"temperature": 0.4 if image else 0.5, "maxOutputTokens": 8192, "responseMimeType": "application/json"}
        if "2.5" in model:
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        parts = [{"text": prompt}]
        if image:
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image}})
        body = {"systemInstruction": {"parts": [{"text": _SYSTEM}]},
                "contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                res = _post_json(url, body, {"x-goog-api-key": GEMINI_API_KEY}, timeout=90 if image else 60)
                parts_out = ((res.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                text = "".join(str(p.get("text", "")) for p in parts_out).strip()
                if text:
                    return text
                last = RuntimeError("Gemini returned an empty answer")
                break
            except urllib.error.HTTPError as exc:
                last = RuntimeError(f"Gemini HTTP {exc.code}")
                if exc.code in (500, 503) and attempt == 0:
                    time.sleep(2)
                    continue
                break                                  # 404 / 429 / 400: try the next model
            except Exception as exc:
                last = exc
                break
    raise last or RuntimeError("Gemini failed")


def _ollama(prompt, image=None):
    model = OLLAMA_VISION_MODEL if image else OLLAMA_MODEL
    user = {"role": "user", "content": prompt}
    if image:
        user["images"] = [image]
    payload = {"model": model, "stream": False, "format": "json", "keep_alive": "20m",
               "messages": [{"role": "system", "content": _SYSTEM}, user],
               "options": {"temperature": 0.4 if image else 0.5, "num_ctx": 6144, "num_predict": 4500}}
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


def ask_json(prompt, image=None):
    """Gemini first, then Ollama (vision model when `image` is given). Raises RuntimeError if nothing answers."""
    errors = []
    engines = []
    if GEMINI_API_KEY and time.time() >= _ai_off_until[0]:
        engines.append(("Gemini", _gemini))
    engines.append(("Ollama", _ollama))
    for name, fn in engines:
        gemini_failed = False
        for _ in range(2):
            try:
                data = _parse_json(fn(prompt, image))
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:120]}")
                gemini_failed = name == "Gemini"
                if name == "Ollama" and isinstance(exc, (urllib.error.URLError, ConnectionError)):
                    break
        if gemini_failed:
            _ai_off_until[0] = time.time() + 120        # skip Gemini for 2 minutes after a failure
    raise RuntimeError("No AI model answered (" + "; ".join(errors[-3:]) + ")")


def ai_available():
    if GEMINI_API_KEY and time.time() >= _ai_off_until[0]:
        return True
    try:
        base = OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags"
        with urllib.request.urlopen(base, timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
        return any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL.split(":")[0] for n in names)
    except Exception:
        return False


# ==================================================
# 2b. UNDERSTANDING WHAT THE USER GAVE US (picture / text -> kind + topic + facts)
# ==================================================
_RESUME_HINTS = ("curriculum vitae", "resume", "résumé", "objective", "professional summary", "career objective",
                 "work experience", "experience", "education", "skills", "projects", "certifications", "achievements",
                 "references", "linkedin", "github", "internship", "declaration", "personal details", "languages known")
_DOC_HINTS = r"\b(dear sir|dear madam|invoice|sincerely|yours faithfully|yours sincerely|subject:|terms and conditions|" \
             r"agreement|certificate|receipt|notice|circular|hereby|bill to)\b"
_HEADING_WORDS = {"curriculum vitae", "resume", "résumé", "cv", "profile", "objective", "education", "skills",
                  "summary", "contact", "personal details", "experience"}
_GENERIC_TOPICS = {"image", "picture", "photo", "png", "jpg", "jpeg", "file", "screenshot", "document", "untitled",
                   "an image", "a picture", "a photo", "unknown", "none"}


def classify_text(text):
    """Heuristic: 'resume', 'document' or 'educational'."""
    low = str(text or "").lower()
    hits = sum(1 for h in _RESUME_HINTS if re.search(r"\b" + re.escape(h) + r"\b", low))
    contact = bool(re.search(r"[\w.+-]+@[\w-]+\.\w+", low)) or bool(re.search(r"(?:\+?\d[\s().-]?){10,}", low))
    if hits >= 4 or (hits >= 3 and contact):
        return "resume"
    if re.search(_DOC_HINTS, low) and hits < 3:
        return "document"
    return "educational"


def _scrub_contacts(text):
    """Remove e-mail addresses, links and phone numbers so they are never spoken or shown."""
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", " ", str(text or ""))
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)
    t = re.sub(r"\+?(?:\d[\s().-]?){10,}", " ", t)
    return t


def guess_topic(text, kind):
    """Topic without any AI: the person's name for a resume, else the first heading-like line."""
    lines = [l.strip(" \t•-|:") for l in str(text or "").splitlines() if l.strip()]
    if kind == "resume":
        for l in lines[:10]:
            w = l.split()
            if 2 <= len(w) <= 4 and l.lower() not in _HEADING_WORDS and not re.search(r"[@\d:/]", l) \
                    and all(x[:1].isalpha() for x in w):
                return l.title() if l.isupper() else l
        return None
    for l in lines[:5]:
        if 2 <= len(l.split()) <= 10 and "@" not in l:
            return l[:80]
    return " ".join(str(text or "").split()[:6]) or None


def _clean_block(text, limit):
    t = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    return re.sub(r"\n{3,}", "\n\n", t)[:limit]


def _looks_like_filename(topic):
    t = str(topic or "").strip().lower()
    return bool(re.search(r"\.(png|jpe?g|webp|bmp|gif|pdf|txt)$", t)) or t in _GENERIC_TOPICS \
        or bool(re.fullmatch(r"(img|image|photo|screenshot|scan|pic)[\s_\-]*\d*", t))


# Shown to the user when a picture is not learning material (or cannot be read at all).
NOT_EDUCATIONAL_MSG = ("I can't read this file. Please upload an educational image "
                       "(a diagram, chart, map, textbook or notes page, or a science / maths / history picture).")

# The picture is analysed only once per file: app.py checks it before charging credits,
# and the video pipeline reuses the same answer.
_analysis_cache = {}

IMAGE_PROMPT = """
Look carefully at this picture and work out WHAT IT SHOWS. The person gave no explanation, so you must understand it.

Decide the kind:
 "educational" = a diagram, labelled figure, chart, graph, map, equation / maths / science / history / language page,
                 textbook or notes page, experiment, or a photo that clearly illustrates a school or college concept.
 "resume"      = a resume, CV, biodata or professional profile page.
 "document"    = a letter, report, certificate, notice, form, invoice, slide, poster or other paper document.
 "general"     = an ordinary photo of an object, animal, plant, food, place, building, vehicle, machine or product.

Return JSON exactly like this:
{"kind": "educational",
 "topic": "short English topic of 2 to 6 words",
 "description": "a detailed factual description of what the picture shows: every label, part, step, number, relationship and what it teaches (up to 250 words)",
 "visible_text": "all readable text in the picture, copied as written (empty string if none)"}

Rules for "topic":
 - educational: the concept shown, e.g. "Human Heart Structure", "Photosynthesis", "Ohm's Law", "Water Cycle".
 - resume: the person's full name as written on it (for example "Anita Sharma").
 - document: what the document is, e.g. "Internship Offer Letter", "Electricity Bill".
 - general: the subject, e.g. "Peacock", "Solar Panel".
 - NEVER answer with "image", "picture", "photo", "PNG" or "file". Name the real subject.
 - Do NOT identify real people from their faces; describe them only. Names may be taken from printed text.
 - Use "educational" ONLY when the picture is clearly learning material (diagram, labelled figure, chart, map, textbook / notes page, experiment, concept illustration).
 - A photo of a person (selfie, portrait, passport photo), a resume, a bill, a product, a random object or scenery is NOT educational.
"""


def _norm_analysis(data):
    if not isinstance(data, dict):
        return None
    k = str(data.get("kind", "")).lower()
    if "resume" in k or k in ("cv", "biodata"):
        kind = "resume"
    elif "educ" in k or any(x in k for x in ("diagram", "chart", "textbook", "lesson", "science")):
        kind = "educational"
    elif any(x in k for x in ("doc", "letter", "report", "certificate", "form", "invoice", "poster", "notice")):
        kind = "document"
    else:
        kind = "general"
    desc = _clean_block(data.get("description"), 2500)
    vis = _clean_block(data.get("visible_text"), 6000)
    if kind != "resume" and classify_text(vis) == "resume":
        kind = "resume"
    topic = _tidy(data.get("topic"))[:80]
    if not topic or topic.lower() in _GENERIC_TOPICS or re.search(r"\b(png|jpe?g)\b", topic.lower()):
        topic = " ".join(_tidy(desc).split()[:5]) if desc else ""
    if not topic and not desc and not vis:
        return None
    return {"kind": kind, "topic": topic, "description": desc, "visible_text": vis}


def _analyze_image_uncached(path):
    try:
        b64 = _image_b64(path)
        res = _norm_analysis(ask_json(IMAGE_PROMPT, image=b64))
        if res:
            return res
    except Exception as exc:
        logger.warning("Vision AI could not read the picture (%s). Trying OCR.", str(exc)[:160])
    text = ""
    try:
        text = extract_text(path)
    except Exception:
        text = ""
    if len(text.split()) >= 15:                              # OCR found real text
        kind = classify_text(text)
        return {"kind": kind, "topic": guess_topic(text, kind) or "", "description": "",
                "visible_text": _clean_block(text, 6000)}
    raise ValueError(NOT_EDUCATIONAL_MSG)


def analyze_image(path):
    """
    Understand an uploaded picture with NO help from the user.
    Returns {kind, topic, description, visible_text}. Raises ValueError(NOT_EDUCATIONAL_MSG) if it cannot be read.
    The answer is cached per file, so the AI is asked only once.
    """
    key = str(path)
    if key not in _analysis_cache:
        _analysis_cache[key] = _analyze_image_uncached(path)
    return _analysis_cache[key]


def check_educational_image(path):
    """Only educational pictures may become a video.

    app.py calls this BEFORE charging credits. Raises ValueError(NOT_EDUCATIONAL_MSG) for everything else
    (your own photo, a resume, a bill, a product, scenery, a picture that cannot be read ...).
    Returns the analysis dict when the picture is educational.
    """
    info = analyze_image(path)
    if info["kind"] != "educational":
        raise ValueError(NOT_EDUCATIONAL_MSG)
    return info


# ==================================================
# 3. SCRIPT
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


def _clean_scene(sc, language, n_labels, kind="educational"):
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
    q = re.sub(r"[\"'\n\r]", " ", str(sc.get("image_query") or "")).strip()[:60]
    qa = re.sub(r"[\"'\n\r]", " ", str(sc.get("image_query_alt") or "")).strip()[:40]
    # photo only for physical things; abstract ideas get a drawn concept card
    visual = "diagram" if str(sc.get("visual", "")).lower().startswith("diag") else "photo"
    if kind in ("resume", "document"):
        visual = "photo"
    if not q:
        visual = "diagram" if kind in ("educational", "general") else visual
    example = None
    ex = sc.get("example")
    if kind in ("educational", "general") and isinstance(ex, dict):
        given, result = _tidy(ex.get("given"))[:70], _tidy(ex.get("result"))[:70]
        if given and result:
            example = {"given": given, "result": result}
    return {"title": title[:80], "narration": narration, "labels": labels, "key_term": term,
            "image_query": q, "image_query_alt": qa, "visual": visual, "example": example}


def plan_length(minutes, language, difficulty, rate_pct=0):
    total = max(30.0, minutes * 60.0)
    n = max(4, min(60, int(round(total / SECONDS_PER_SCENE))))
    # a slower voice speaks fewer words per minute, so write fewer words and the video still fits the minutes
    wpm = WORDS_PER_MINUTE.get(language.lower(), 140) * (100 + rate_pct) / 100.0
    words = int((total - n * PAUSE) / 60.0 * wpm / n * LEVEL_WORDS[difficulty])
    return n, max(25, words)


def _first_note(kind, topic, language):
    return {
        "educational": f"Scene 1: its title is the question 'What is {topic}?' (in {language}) and its narration "
                       "starts with a plain definition, then a hook from real life and the learning objective.",
        "general": f"Scene 1: its title names the subject '{topic}' (in {language}) and its narration starts with one "
                   "plain sentence saying what it is, then why it is interesting.",
        "resume": f"Scene 1: its title is 'Meet {topic}' (in {language}); its narration introduces the person, their field "
                  "and what the video will cover.",
        "document": f"Scene 1: its title says what the document is (in {language}); its narration states its purpose.",
    }[kind]


def _last_note(kind, audience):
    return {
        "educational": "The LAST scene is the final summary of the important points with a meaningful conclusion"
                       + (" plus one classroom activity and one check-for-understanding question."
                          if audience == "Teachers" else "."),
        "general": "The LAST scene is a final summary of the key points.",
        "resume": "The LAST scene is a confident closing: the person's main strengths and career goal (facts from the source only).",
        "document": "The LAST scene gives the conclusion and any action points.",
    }[kind]


def write_script_ai(topic, source, audience, difficulty, language, style, n, words, kind="educational", progress=None):
    n_labels = LEVEL_LABELS[difficulty]
    info = KIND_INFO[kind]
    rules = TEACHING_RULES[(audience, difficulty)] if kind in ("educational", "general") else info["rules"]
    style_text = STYLE_RULES[style] if kind in ("educational", "general") else STYLE_RULES["Presenter"]
    narr_rule = info["narr"].replace("{words}", str(words))
    teaching = kind in ("educational", "general")
    if teaching:
        visual_rule = ("- visual: 'photo' ONLY if the scene is about a physical thing a camera can photograph (an organ, animal, "
                       "plant, machine, place, material, experiment). Use 'diagram' for software, computers, maths, "
                       "processes, algorithms, rules and every abstract idea. When unsure choose 'diagram'.")
        example_rule = ("- example: a REAL, concrete, correct worked example with actual values taken from the topic, "
                        "as {\"given\": \"...\", \"result\": \"...\"}, each at most 8 words, in " + language + ". "
                        "Examples: given 'I love cats' result 'I | love | cats' (tokenizing); given 'Water at 100 degrees C' "
                        "result 'It boils into steam'; given '2 + 3 x 4' result '14, multiply first'. "
                        "The narration's last sentence says this same example. Never vague (no 'something happens'). "
                        "The title, labels and example are about the REAL topic, never about a comparison.")
        analogy_rule = ("- A familiar comparison (lunch box, cricket ball ...) may appear ONLY inside the narration and must be "
                        "introduced as 'it is like ...'. Never use it as a title, label, image_query or example.")
    else:
        visual_rule = "- visual: always 'photo'."
        example_rule = "- example: null."
        analogy_rule = ""
    scenes, title, rounds = [], "", 0
    per = 6
    while len(scenes) < n and rounds < n + 6:
        rounds += 1
        first = len(scenes)
        count = min(per, n - first)
        covered = "; ".join(s["title"] for s in scenes) or "none yet"
        last_note = _last_note(kind, audience) if first + count >= n else "Do NOT write the final summary yet."
        first_note = _first_note(kind, topic, language) if first == 0 else ""
        src = (f"\nSOURCE MATERIAL (use its facts, never invent):\n{source[:7000]}\n") if source else ""
        prompt = f"""
Write scenes {first + 1} to {first + count} of a {n}-scene {info['noun']} about: {topic}
{src}
AUDIENCE: {audience}.  LEVEL: {difficulty}.  RULES: {rules}
STYLE: {style}. {style_text}
LANGUAGE: {language}. {LANGUAGE_NOTE[language.lower()]}

Video order: {info['flow']} Do not repeat scenes.
Already written (do not repeat): {covered}
{first_note} {last_note}

Rules for every scene:
- title: a short question or a 3 to 5 word phrase about ONE idea, in {language}.
- narration: {narr_rule}
{visual_rule}
- {info['query']}
  image_query_alt: ENGLISH 1-3 words, the main physical object (empty when visual is 'diagram').
- labels: exactly {n_labels} key points, each at most 4 words, in the order the narration mentions them, in {language}.
- key_term: one important term with a one-sentence definition, in {language}.
{example_rule}
{analogy_rule}
- Everything must be factually correct. If you are not sure of a fact, leave it out.

Return JSON exactly like this:
{{"title": "Video title in {language}",
  "scenes": [{{"title": "...", "narration": "...", "visual": "diagram", "image_query": "", "image_query_alt": "",
              "labels": ["one", "two", "three"],
              "key_term": {{"term": "...", "definition": "..."}},
              "example": {{"given": "...", "result": "..."}}}}]}}
"""
        data = ask_json(prompt)
        title = title or _tidy(data.get("title"))
        for sc in data.get("scenes") or []:
            c = _clean_scene(sc, language, n_labels, kind)
            if c and _script_ratio(c["narration"], language) >= 0.6:
                scenes.append(c)
                if len(scenes) >= n:
                    break
        if progress:
            progress(len(scenes) / n, "Writing the lesson")
    if len(scenes) < max(3, n // 2):
        raise RuntimeError(f"The AI could not write the lesson in {language}.")
    return title or topic, scenes


# ---- built-in algorithm (no AI model): Wikipedia / your text -> scenes ----
_STOP = set("""a an the of in on and with for to is are was were be been being that this these those it its as at by from or
not but can will which who whom what when where how why also into than then there their they them have has had do does did
such more most other some any all each both between about over under after before during while using used use may might""".split())
_OFFICE_QUERIES = ["professional office work", "team meeting office", "laptop desk work", "university students",
                   "business handshake"]


def _wikipedia_text(topic, max_chars=9000):
    try:
        qs = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrsearch": topic, "gsrlimit": 1,
                                     "prop": "extracts", "explaintext": 1, "exlimit": 1, "format": "json",
                                     "redirects": 1})
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


def write_script_algo(topic, source, audience, difficulty, language, n, words, kind="educational"):
    """Own algorithm: pick the sentences of the source text, group them into scenes, label them."""
    text = source or ""
    if kind in ("educational", "general") and len(text.split()) < 120:
        text = _wikipedia_text(topic) or text
    if kind in ("resume", "document"):                      # these have lines, not sentences
        raw = [s.strip(" -•\t") for s in re.split(r"[\n\r]+|(?<=[.!?])\s+", text)]
        sentences = [s for s in raw if len(s.split()) >= 4 and "@" not in s]
        min_needed = 3
    else:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if len(s.split()) >= 6]
        min_needed = 6
    if len(sentences) < min_needed:
        raise RuntimeError("No AI model is running and no source text could be found for this topic. "
                           "Add GEMINI_API_KEY, start Ollama, or paste some text about the topic.")
    if language.lower() != "english" and not _translator_ok():
        raise RuntimeError(f"{language} needs an AI model (Gemini / Ollama) or: pip install deep-translator")
    n = max(2, min(n, len(sentences) // 2))
    per_words = max(25, words)
    groups, cur, cnt = [], [], 0
    for s in sentences:
        if len(groups) >= n:                 # enough scenes: ignore the rest so the video keeps its length
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
            ttl = f"What is {topic}?" if kind in ("educational", "general") else f"About {topic}"
        elif i == len(groups) - 1:
            ttl = "Summary"
        else:
            ttl = keys[0].capitalize()
        first_def = next((s for s in g if re.search(r"\b(is|are|refers to|means)\b", s)), g[0])
        if kind in ("resume", "document"):
            q, qa = _OFFICE_QUERIES[i % len(_OFFICE_QUERIES)], "office"
        else:
            q, qa = (topic if i == 0 else f"{keys[0]} {topic}"), topic
        scenes.append({"title": ttl, "narration": narr, "labels": [k.capitalize() for k in keys],
                       "key_term": {"term": keys[0].capitalize(), "definition": first_def[:140]},
                       "image_query": q, "image_query_alt": qa, "visual": "photo", "example": None})
    title = topic[:1].upper() + topic[1:]
    if language.lower() != "english":
        tgt = LANG_CODES[language.lower()]
        for sc in scenes:
            for k in ("title", "narration"):
                sc[k] = _translate(sc[k], tgt)
            sc["labels"] = [_translate(x, tgt) for x in sc["labels"]]
            sc["key_term"] = {"term": _translate(sc["key_term"]["term"], tgt),
                              "definition": _translate(sc["key_term"]["definition"], tgt)}
        title = _translate(title, tgt)
    return title, scenes


def build_script(topic, source, audience, difficulty, language, style, minutes, kind="educational", progress=None,
                 rate_pct=0):
    n, words = plan_length(minutes, language, difficulty, rate_pct)
    if kind in ("resume", "document") and source:           # a short page cannot fill a long video
        n = min(n, max(3, len(source.split()) // 35))
    if ai_available():
        try:
            title, scenes = write_script_ai(topic, source, audience, difficulty, language, style, n, words, kind,
                                            progress)
            return title, scenes, "ai"
        except Exception as exc:
            logger.warning("AI script failed (%s). Using the built-in algorithm.", exc)
    title, scenes = write_script_algo(topic, source, audience, difficulty, language, n, words, kind)
    return title, scenes, "algorithm"


# ==================================================
# 4. VOICE CREATION  (neural edge-tts; gTTS = female fallback only)
# ==================================================
VOICES = {
    "english": {"female": ["en-US-AvaMultilingualNeural", "en-US-JennyNeural", "en-IN-NeerjaNeural"],
                "male": ["en-US-AndrewMultilingualNeural", "en-US-GuyNeural", "en-IN-PrabhatNeural"]},
    "kannada": {"female": ["kn-IN-SapnaNeural"], "male": ["kn-IN-GaganNeural"]},
    "hindi": {"female": ["hi-IN-SwaraNeural"], "male": ["hi-IN-MadhurNeural"]},
}
VOICE_RATE = {"School Students": -4, "College Students": 0, "Teachers": -2}      # % speed per audience
SOFT_RATE = -18                                  # School + Beginner: clearly slower than normal speech


def voice_style(audience, difficulty):
    """-> (rate_pct, soft). School Students + Beginner get a slow, soft, gentle teacher voice."""
    if audience == "School Students" and difficulty == "Beginner":
        return SOFT_RATE, True
    return VOICE_RATE.get(audience, 0), False


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


def generate_narration(text, out_path, language="English", voice="Female", rate_pct=0, soft=False):
    """Record one scene. soft=True -> slightly quieter and lower pitch for a gentle voice.
    Male voice never falls back to the female gTTS voice (clear error instead)."""
    text = _clean_for_speech(text)
    if not text:
        raise ValueError("Narration text is empty.")
    out = Path(out_path)
    last = None
    if edge_tts_available():
        import edge_tts

        extra = {"volume": "-8%", "pitch": "-2Hz"} if soft else {}

        async def run(name):
            await edge_tts.Communicate(text, name, rate=f"{int(rate_pct):+d}%", **extra).save(str(out))

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
        raise RuntimeError("The male voice needs the neural voice engine: pip install edge-tts, and check the "
                           f"internet connection. ({last or 'edge-tts not installed'}) gTTS only has a female voice.")
    try:
        from gtts import gTTS
        with _tts_lock:
            _tts_stats["fallbacks"] += 1
        gTTS(text=text, lang=LANG_CODES[language.lower()], slow=bool(soft)).save(str(out))
    except Exception as exc:
        raise RuntimeError(f"Could not create the voice (needs internet): {exc}") from exc
    return str(out)


# ==================================================
# 5. PHOTOS  (only for physical subjects; every photo is checked against its own title / tags)
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


def _relevant(label, words):
    """A photo is accepted when its title / tags mention the subject (or when the source gives no text)."""
    label = str(label or "").lower()
    if not label or not words:
        return True
    return any(w.rstrip("s")[:max(3, len(w) - 1)] in label for w in words if len(w) >= 3)


def _s_pexels(q, portrait):
    if not PEXELS_API_KEY:
        return []
    qs = urllib.parse.urlencode({"query": q, "per_page": 8, "orientation": "portrait" if portrait else "landscape"})
    d = json.loads(_get("https://api.pexels.com/v1/search?" + qs, headers={"Authorization": PEXELS_API_KEY}))
    return [(p["src"].get("large") or p["src"].get("medium"), "Pexels", p.get("alt", "")) for p in d.get("photos", [])
            if p.get("src")]


def _s_pixabay(q, portrait):
    if not PIXABAY_API_KEY:
        return []
    qs = urllib.parse.urlencode({"key": PIXABAY_API_KEY, "q": q, "image_type": "photo", "per_page": 8,
                                 "safesearch": "true", "min_width": MIN_PHOTO_W})
    d = json.loads(_get("https://pixabay.com/api/?" + qs))
    return [(h.get("largeImageURL") or h.get("webformatURL"), "Pixabay", h.get("tags", "")) for h in d.get("hits", [])]


def _s_wikipedia(q, portrait):
    qs = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrsearch": q, "gsrlimit": 6,
                                 "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 1280, "format": "json"})
    d = json.loads(_get("https://en.wikipedia.org/w/api.php?" + qs))
    pages = sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        th, low = p.get("thumbnail") or {}, p.get("title", "").lower()
        if th.get("source") and th.get("width", 0) >= MIN_PHOTO_W and not any(b in low for b in _BAD_TITLE):
            out.append((th["source"], "Wikipedia", low))
    return out[:3]


def _s_commons(q, portrait):
    qs = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {q}",
                                 "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|size|mime",
                                 "iiurlwidth": 1280, "format": "json"})
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
        out.append((info.get("thumburl") or info.get("url"), "Wikimedia Commons", title))
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
    """Return the photo source name, or None. Stops after `budget` seconds. `used` = urls already taken by this video.
    A photo whose own title / tags do not match the query words is skipped (no more watch gears for a computer lesson)."""
    used = used if used is not None else set()
    deadline = time.time() + budget
    for q in dict.fromkeys(x.strip() for x in queries if x and x.strip()):
        words = _words(q)
        for search in (_s_pexels, _s_pixabay, _s_wikipedia, _s_commons):
            if time.time() > deadline:
                return None
            try:
                for url, source, label in search(q, portrait):
                    if time.time() > deadline:
                        return None
                    if not _relevant(label, words):
                        continue
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
# 6. FFMPEG
# ==================================================
def get_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"):
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("FFmpeg was not found. Install it and add it to PATH.")


def run_ffmpeg(cmd, label):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg {label} failed: " + r.stderr[-1200:])


def get_duration(path, ffmpeg):
    r = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def _ff(path):
    return Path(path).resolve().as_posix().replace("'", "'\\''")


# ==================================================
# 7. PAINTER: classroom look (drawn with Pillow). NO person / mascot is drawn.
# ==================================================
# a1 = chip / newest pill colour, a2 = glow behind the picture. Different per audience so the editions look different.
PALETTES = {
    "School Students": dict(a1=(255, 196, 0), a2=(0, 168, 232)),
    "College Students": dict(a1=(255, 150, 60), a2=(120, 100, 235)),
    "Teachers": dict(a1=(70, 200, 150), a2=(0, 170, 150)),
}
ACCENTS = [(255, 99, 132), (54, 162, 235), (255, 170, 0), (34, 197, 148), (153, 102, 255)]
WHITE, INK, NAVY, BLUE, YELLOW = (255, 255, 255), (30, 30, 70), (14, 24, 70), (30, 100, 220), (255, 205, 20)

_FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
              "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
_FONT_NAMES = {
    "latin": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "latin_bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "indic": ["Nirmala.ttf", "Nirmala.ttc", "NirmalaUI.ttf", "NotoSansKannada-Regular.ttf",
              "NotoSansDevanagari-Regular.ttf", "Lohit-Kannada.ttf", "Lohit-Devanagari.ttf"],
    "indic_bold": ["NirmalaB.ttf", "NirmalaB.ttc", "Nirmala.ttf", "NotoSansKannada-Bold.ttf",
                   "NotoSansDevanagari-Bold.ttf"],
}


@lru_cache(maxsize=None)
def _find_font(kind):
    for name in _FONT_NAMES[kind]:
        for base in _FONT_DIRS:
            b = Path(base)
            if not b.exists():
                continue
            if (b / name).is_file():
                return str(b / name)
            if not base.startswith("C:"):
                try:
                    hit = next(b.rglob(name), None)
                except OSError:
                    hit = None
                if hit:
                    return str(hit)
    return None


def _use_shaper():
    """True when Kannada / Hindi must be drawn by services/indic_text.py (HarfBuzz) because Pillow has no RAQM."""
    return bool(indic_text and indic_text.AVAILABLE and not indic_text.RAQM)


@lru_cache(maxsize=512)
def _font(size, bold, indic):
    if indic and _use_shaper():
        path = _find_font("indic_bold" if bold else "indic") or _find_font("indic")
        if path:
            try:
                return indic_text.ShapedFont(path, int(size))
            except Exception:
                logger.warning("HarfBuzz could not open %s; using Pillow's own text drawing.", path, exc_info=True)
    kinds = ([("indic_bold" if bold else "indic")] if indic else []) + [("latin_bold" if bold else "latin")]
    for kind in kinds:
        path = _find_font(kind)
        if path:
            try:
                return ImageFont.truetype(path, int(size))
            except OSError:
                pass
    try:
        return ImageFont.load_default(int(size))
    except TypeError:
        return ImageFont.load_default()


class _Measure:
    """Measures text width for normal Pillow fonts and for the HarfBuzz fonts of indic_text.ShapedFont."""
    _d = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def textlength(self, text, font):
        if hasattr(font, "advance"):
            return font.advance(text)
        return self._d.textlength(text, font=font)


_SCRATCH = _Measure()


def _put(d, xy, text, font, fill):
    """Draw text with either kind of font."""
    if hasattr(font, "mask"):
        indic_text.draw_text(d, xy, text, font, fill)
    else:
        d.text(xy, text, font=font, fill=fill)


def _wrap(text, font, max_w):
    lines, cur = [], ""
    for w in str(text).split():
        trial = (cur + " " + w).strip()
        if _SCRATCH.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _tok(word):
    return str(word).strip(".,;:!?\"'()[]{}\u0964\u0965-\u2013\u2014?").lower()


def text_box(d, text, box, fill, max_size, min_size=12, bold=True, align="center", indic=False,
             hl=None, hl_fill=None):
    """Fit `text` into `box`. Words whose lower-case form is in `hl` are drawn in `hl_fill`."""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    gap = 1.45 if indic else 1.2
    size = int(max_size)
    while True:
        f = _font(size, bold, indic)
        lines = _wrap(text, f, w)
        if (len(lines) * int(size * gap) <= h and all(_SCRATCH.textlength(l, font=f) <= w for l in lines)) \
                or size <= min_size:
            break
        size = max(min_size, size - 2)
    lh = int(size * gap)
    y = y0 + (h - len(lines) * lh) / 2
    space = _SCRATCH.textlength(" ", font=f)
    for line in lines:
        if hl:
            parts = line.split(" ")
            total = sum(_SCRATCH.textlength(p, font=f) for p in parts) + space * (len(parts) - 1)
            x = x0 + (w - total) / 2 if align == "center" else x0
            for p in parts:
                _put(d, (x, y), p, f, (hl_fill if _tok(p) in hl else fill))
                x += _SCRATCH.textlength(p, font=f) + space
        else:
            lw = _SCRATCH.textlength(line, font=f)
            _put(d, (x0 + (w - lw) / 2 if align == "center" else x0, y), line, f, fill)
        y += lh


def _mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _sparkle(d, cx, cy, s, fill):
    d.polygon([(cx, cy - 2 * s), (cx + .5 * s, cy - .5 * s), (cx + 2 * s, cy), (cx + .5 * s, cy + .5 * s),
               (cx, cy + 2 * s), (cx - .5 * s, cy + .5 * s), (cx - 2 * s, cy), (cx - .5 * s, cy - .5 * s)], fill=fill)


_bg_cache = {}


def make_background(size):
    """Soft, blurred classroom: sky-blue wall, bookshelf on the left, window on the right."""
    if size in _bg_cache:
        return _bg_cache[size]
    W, H = size
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_mix((176, 212, 242), (238, 247, 252), y / max(1, H - 1)))
    L = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(L)
    ld.rectangle([0, H * .12, W * .09, H * .80], fill=(190, 150, 110, 255))
    for row in range(4):
        yy = H * .16 + row * H * .16
        xx = W * .008
        k = 0
        while xx < W * .08:
            bw = W * (.008 + .008 * ((k * 7 + row * 3) % 5) / 4)
            ld.rectangle([xx, yy, xx + bw, yy + H * .12], fill=ACCENTS[(k + row) % 5] + (255,))
            xx += bw + 2
            k += 1
        ld.rectangle([0, yy + H * .12, W * .09, yy + H * .135], fill=(150, 110, 80, 255))
    ld.rectangle([W * .74, H * .08, W * .97, H * .46], fill=(255, 255, 255, 255))
    ld.rectangle([W * .75, H * .10, W * .96, H * .44], fill=(170, 220, 250, 255))
    ld.line([(W * .855, H * .10), (W * .855, H * .44)], fill=(255, 255, 255, 255), width=max(2, int(W * .006)))
    L = L.filter(ImageFilter.GaussianBlur(H * 0.012))
    img = Image.alpha_composite(img.convert("RGBA"), L).convert("RGB")
    _bg_cache[size] = img
    return img


def _badge(d, cx, cy, r, idx, number):
    acc = ACCENTS[idx % len(ACCENTS)]
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=acc, outline=WHITE, width=3)
    f = _font(max(8, int(r * 1.15)), True, False)
    s = str(number)
    d.text((cx - d.textlength(s, font=f) / 2, cy - r * .68), s, font=f, fill=WHITE)


class SceneRenderer:
    """Draws every frame of one scene: picture / concept card, title, point pills, real-example box,
    caption and the small AI robot. No person or mascot."""

    def __init__(self, size, audience, level, language, style, subtitles, voice="Female", kind="educational",
                 has_example=False):
        self.W, self.H = size
        self.portrait = self.H > self.W
        self.audience, self.level = audience, level
        self.kind = kind
        self.lang = language.lower()
        self.label = KIND_LABEL.get(kind, AUDIENCE_TAG[audience])
        self.indic = language.lower() in SCRIPT_RANGES
        self.subtitles = subtitles
        self.pal = PALETTES[audience]
        self.bg = make_background(size)
        W, H = self.W, self.H
        self.m = int(W * .05)
        self.top = int(H * .035)
        self.head_h = int(H * (0.115 if not self.portrait else 0.10))
        self.tag_row = int(H * .045) if self.portrait else 0
        self.cap_h = int(H * (0.21 if not self.portrait else 0.19)) if subtitles else 0
        vt = self.top + self.head_h + self.tag_row + int(H * .025)
        vb = H - self.cap_h - int(H * .035)
        x0, x1 = self.m, W - self.m
        gap = 14
        self.example_box = None
        if self.portrait:
            span = vb - vt
            self.robot_h = int(H * .20)
            ph_h = int(span * (.30 if has_example else .44))
            self.photo_box = (x0, vt, x1, vt + ph_h)
            cur = vt + ph_h + gap
            if has_example:
                eh = int(span * .17)
                self.example_box = (x0, cur, x1, cur + eh)
                cur += eh + gap
            self.panel = (x0, cur, x1, vb - int(H * .06))
            self.cap_x1 = W - self.m
        else:
            w = x1 - x0
            px0, px1 = x0 + int(w * .02), x0 + int(w * .66)
            self.robot_h = int(H * .36)
            ph_h = int((vb - vt) * (.66 if has_example else 1.0))
            self.photo_box = (px0, vt, px1, vt + ph_h)
            if has_example:
                self.example_box = (px0, vt + ph_h + gap, px1, vb)
            self.panel = (px1 + gap * 2, vt, x1, min(vb, H - self.robot_h - int(H * .02)))
            self.cap_x1 = W - int(self.robot_h * .8) - int(self.m * .15) - 14
        self.canvas = None
        self.mask = None
        # soft glow behind the picture bubble (alpha mask made once, brightness pulses per frame)
        bx0, by0, bx1, by1 = self.photo_box
        mg = int(H * .06)
        self.glow_pos = (bx0 - mg, by0 - mg)
        gm = Image.new("L", (bx1 - bx0 + 2 * mg, by1 - by0 + 2 * mg), 0)
        ImageDraw.Draw(gm).rounded_rectangle([mg - 6, mg - 6, gm.width - mg + 6, gm.height - mg + 6], 44, fill=255)
        self.glow_mask = gm.filter(ImageFilter.GaussianBlur(H * .02))

    # ---------- photo ----------
    def load_photo(self, path):
        x0, y0, x1, y1 = self.photo_box
        fw, fh = x1 - x0 - 8, y1 - y0 - 8
        self.pw, self.ph = fw, fh
        bw, bh = int(fw * 1.2), int(fh * 1.2)
        with Image.open(path) as im:
            im = im.convert("RGB")
            cover = max(bw / im.width, bh / im.height)
            bg = im.resize((max(bw, int(im.width * cover)), max(bh, int(im.height * cover))), Image.LANCZOS)
            l, t = (bg.width - bw) // 2, (bg.height - bh) // 2
            bg = bg.crop((l, t, l + bw, t + bh)).filter(ImageFilter.GaussianBlur(10))
            bg = Image.blend(bg, Image.new("RGB", bg.size, (10, 12, 28)), 0.45)
            fit = min(bw / im.width, bh / im.height)
            fg = im.resize((max(1, int(im.width * fit)), max(1, int(im.height * fit))), Image.LANCZOS)
            fg = fg.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))
            bg.paste(fg, ((bw - fg.width) // 2, (bh - fg.height) // 2))
        self.canvas = bg
        mask = Image.new("L", (fw, fh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], 38, fill=255)
        self.mask = mask

    def paste_photo(self, img, p, pan):
        z = 1.0 + 0.14 * (p * p * (3 - 2 * p))
        bw, bh = self.canvas.size
        ww, wh = bw / z, bh / z
        sx, sy = bw - ww, bh - wh
        px, py = sx * (0.5 + pan * 0.4 * (0.5 - p)), sy * 0.5
        crop = self.canvas.resize((self.pw, self.ph), Image.BICUBIC, box=(px, py, px + ww, py + wh))
        img.paste(crop, (self.photo_box[0] + 4, self.photo_box[1] + 4), self.mask)

    # ---------- words to highlight ----------
    @staticmethod
    def _hl_words(scene):
        words = set()
        for w in str(scene["key_term"].get("term", "")).split():
            words.add(_tok(w))
        for lab in scene["labels"]:
            for w in str(lab).split():
                if len(_tok(w)) >= 4:
                    words.add(_tok(w))
        return {w for w in words if w and w not in _STOP}

    @staticmethod
    def _title_hl(title, term):
        toks = [_tok(w) for w in str(title).split() if _tok(w)]
        term_toks = {_tok(w) for w in str(term).split()}
        hit = {t for t in toks if t in term_toks and t not in _STOP and len(t) >= 3}
        if not hit:
            cand = [t for t in toks if t not in _STOP and len(t) >= 4] or toks
            hit = {max(cand, key=len)} if cand else set()
        return hit

    # ---------- "real example" box:  GIVEN  ->  RESULT ----------
    def _draw_example(self, d, scene, show):
        x0, y0, x1, y1 = self.example_box
        pal = self.pal
        d.rounded_rectangle([x0 + 4, y0 + 6, x1 + 4, y1 + 6], 26, fill=(0, 0, 0, 55))
        d.rounded_rectangle([x0, y0, x1, y1], 26, fill=(255, 255, 255, 245), outline=pal["a1"], width=5)
        h = y1 - y0
        hh = max(22, int(h * .25))
        text_box(d, EXAMPLE_WORD.get(self.lang, "Real example"), (x0 + 24, y0 + 6, x1 - 24, y0 + hh), BLUE,
                 int(hh * .8), 9, True, "left", self.indic)
        if not show:
            return
        ex = scene["example"]
        by0, by1 = y0 + hh + 2, y1 - 14
        mid = (x0 + x1) // 2
        gx = max(24, int((x1 - x0) * .06))
        cols = [((x0 + 16, by0, mid - gx, by1), (226, 238, 255), ACCENTS[1], ex["given"]),
                ((mid + gx, by0, x1 - 16, by1), (220, 246, 232), ACCENTS[3], ex["result"])]
        for box, fill, edge, txt in cols:
            d.rounded_rectangle(box, 20, fill=fill, outline=edge, width=3)
            text_box(d, txt, (box[0] + 12, box[1] + 4, box[2] - 12, box[3] - 4), INK,
                     int((by1 - by0) * .42), 9, True, "center", self.indic)
        ay = (by0 + by1) // 2
        s = max(8, int((by1 - by0) * .16))
        d.line([(mid - gx + 6, ay), (mid + gx - s - 4, ay)], fill=pal["a1"], width=max(4, s // 2))
        d.polygon([(mid + gx - 4, ay), (mid + gx - 4 - s * 1.4, ay - s), (mid + gx - 4 - s * 1.4, ay + s)],
                  fill=pal["a1"])

    # ---------- static layer of one step (title, pills, example, caption) ----------
    def layer(self, scene, idx, total, caption, k, show_ex=False):
        W, H, pal, m = self.W, self.H, self.pal, self.m
        L = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        d = ImageDraw.Draw(L)
        d.rectangle([0, 0, W, 8], fill=(0, 0, 0, 40))
        d.rectangle([0, 0, int(W * (idx + 1) / max(1, total)), 8], fill=pal["a1"])
        # slide counter + tag
        f = _font(max(16, int(H * .03)), True, False)
        counter = f"{idx + 1} / {total}"
        cw = d.textlength(counter, font=f)
        d.text((W - m - cw, self.top + 6), counter, font=f, fill=NAVY)
        tag = self.label if self.kind in KIND_LABEL else f"{self.label} · {self.level.upper()}"
        ft = _font(max(13, int(H * (.028 if not self.portrait else .026))), True, False)
        tw = d.textlength(tag, font=ft)
        if self.portrait:
            py0 = self.top + self.head_h + 2
            d.rounded_rectangle([m, py0, m + tw + 30, py0 + self.tag_row - 6], 12, fill=pal["a1"])
            d.text((m + 15, py0 + int(H * .007)), tag, font=ft, fill=INK)
            reserve = cw + 24
        else:
            tx1 = W - m - cw - 14
            tx0 = tx1 - tw - 22
            d.rounded_rectangle([tx0, self.top + 4, tx1, self.top + 4 + int(H * .043)], 10, fill=pal["a1"])
            d.text((tx0 + 11, self.top + 4 + int(H * .009)), tag, font=ft, fill=INK)
            reserve = cw + tw + 52
        # dark title pill with a yellow key word
        title = scene["title"]
        avail_x0, avail_x1 = m, W - m - reserve
        avail_w = max(120, avail_x1 - avail_x0)
        tsize = int(H * .062)
        need = int(_SCRATCH.textlength(title, font=_font(tsize, True, self.indic))) + 76
        pw = max(120, min(avail_w, max(int(avail_w * .4), need)))
        px0 = avail_x0 + (avail_w - pw) // 2
        py0, py1 = self.top + 4, self.top + self.head_h - 4
        d.rounded_rectangle([px0 + 3, py0 + 5, px0 + pw + 3, py1 + 5], (py1 - py0) // 2, fill=(0, 0, 0, 55))
        d.rounded_rectangle([px0, py0, px0 + pw, py1], (py1 - py0) // 2, fill=NAVY + (245,), outline=WHITE, width=3)
        text_box(d, title, (px0 + 28, py0 + 3, px0 + pw - 28, py1 - 3), WHITE, tsize, 14, True, "center", self.indic,
                 hl=self._title_hl(title, scene["key_term"].get("term", "")), hl_fill=YELLOW)
        # concept card when this scene has no photo (abstract ideas are explained with a drawn card, not a random photo)
        if self.canvas is None:
            x0, y0, x1, y1 = self.photo_box
            bh = y1 - y0
            d.rounded_rectangle([x0, y0, x1, y1], 40, fill=(255, 255, 255, 240), outline=pal["a1"], width=6)
            cx, cy, r = (x0 + x1) / 2, y0 + bh * .24, min(x1 - x0, bh) * .12
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=pal["a1"], outline=WHITE, width=4)
            text_box(d, str(idx + 1), (cx - r, cy - r, cx + r, cy + r), INK, int(r * 1.2), 12, True, "center")
            term = scene["key_term"].get("term") or title
            text_box(d, term, (x0 + 24, cy + r + 10, x1 - 24, cy + r + 10 + bh * .24), BLUE,
                     int(bh * .15), 14, True, "center", self.indic)
            if scene["key_term"].get("definition"):
                text_box(d, scene["key_term"]["definition"], (x0 + 28, y0 + bh * .60, x1 - 28, y1 - 18),
                         INK, int(bh * .09), 10, False, "center", self.indic)
        # numbered point pills (no arrows), the newest one is yellow
        qx0, qy0, qx1, qy1 = self.panel
        labels = scene["labels"]
        n = max(1, len(labels))
        gap = int(H * .012)
        ph = max(28, int(min((qy1 - qy0 - gap * (n - 1)) / n, H * .085)))
        for i in range(min(k, n)):
            y0 = qy0 + i * (ph + gap)
            y1 = y0 + ph
            d.rounded_rectangle([qx0 + 4, y0 + 5, qx1 + 4, y1 + 5], ph // 2, fill=(0, 0, 0, 60))
            d.rounded_rectangle([qx0, y0, qx1, y1], ph // 2, fill=(pal["a1"] if i == k - 1 else WHITE),
                                outline=ACCENTS[i % 5], width=4)
            _badge(d, qx0 + ph // 2, (y0 + y1) // 2, ph * .36, i, i + 1)
            text_box(d, labels[i], (qx0 + int(ph * .85), y0 + 3, qx1 - int(ph * .3), y1 - 3), INK,
                     int(ph * .5), 9, True, "left", self.indic)
        # real example box (content appears when the narration reaches "For example ...")
        if self.example_box and scene.get("example"):
            self._draw_example(d, scene, show_ex)
        # white caption box with highlighted words
        if self.subtitles and caption:
            sh = self.cap_h - int(H * .03)
            cy0 = H - sh - int(H * .025)
            cx0, cx1 = m, self.cap_x1
            d.rounded_rectangle([cx0 + 4, cy0 + 6, cx1 + 4, cy0 + sh + 6], 22, fill=(0, 0, 0, 55))
            d.rounded_rectangle([cx0, cy0, cx1, cy0 + sh], 22, fill=(255, 255, 255, 250), outline=pal["a1"], width=5)
            text_box(d, caption, (cx0 + 22, cy0 + 6, cx1 - 22, cy0 + sh - 6), INK,
                     int(H * (0.05 if not self.portrait else 0.034)), 10, True, "center", self.indic,
                     hl=self._hl_words(scene), hl_fill=BLUE)
        return L

    # ---------- animated parts, drawn on every frame ----------
    def draw_glow(self, frame, T):
        f = .55 + .25 * math.sin(T * 2.2)
        lut = [int(i * f) for i in range(256)]
        g = Image.new("RGBA", self.glow_mask.size, tuple(self.pal["a2"]) + (0,))
        g.putalpha(self.glow_mask.point(lut))
        frame.paste(g, self.glow_pos, g)

    def draw_front(self, frame, T):
        d = ImageDraw.Draw(frame)
        x0, y0, x1, y1 = self.photo_box
        if self.canvas is not None:
            d.rounded_rectangle([x0, y0, x1, y1], 42, outline=WHITE, width=6)
        for i in range(5):                                      # twinkling sparkles circle the picture
            a = T * 0.9 + i * 1.26
            sx = (x0 + x1) / 2 + (x1 - x0) * 0.55 * math.cos(a)
            sy = (y0 + y1) / 2 + (y1 - y0) * 0.55 * math.sin(a)
            s = max(2.0, self.H * 0.012 * (1.2 + math.sin(T * 3 + i)))
            _sparkle(d, sx, sy, s, self.pal["a1"] if i % 2 else WHITE)
        self._draw_robot(frame, T)

    def _draw_robot(self, img, T):
        """AI robot: floats, blinks and points its finger at the picture."""
        H, W = self.H, self.W
        rh = self.robot_h
        rw = int(rh * 0.80)
        S = 2
        w, h = rw * S, rh * S
        L = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(L)
        white, grey, navy, cyan = (248, 250, 255), (196, 206, 228), (16, 24, 64), (70, 226, 255)
        lw = max(2, int(h * 0.012))
        fy = math.sin(T * 2.0) * 0.02 * h
        wag = math.sin(T * 4.0) * .02 * h
        cx = w * .55
        by = .52 * h + fy
        sh_l = (cx - .22 * w, by + .08 * h)
        hand = (cx - .44 * w, by - .12 * h + wag)                # pointing arm
        d.line([sh_l, hand], fill=grey, width=int(.13 * w))
        d.line([sh_l, hand], fill=white, width=int(.095 * w))
        d.ellipse([hand[0] - .075 * w, hand[1] - .06 * h, hand[0] + .075 * w, hand[1] + .06 * h],
                  fill=white, outline=grey, width=lw)
        d.rounded_rectangle([hand[0] - .02 * w, hand[1] - .17 * h, hand[0] + .035 * w, hand[1] - .02 * h],
                            int(.025 * w), fill=white, outline=grey, width=lw)
        sh_r, end_r = (cx + .22 * w, by + .08 * h), (cx + .38 * w, by + .38 * h)
        d.line([sh_r, end_r], fill=grey, width=int(.13 * w))
        d.line([sh_r, end_r], fill=white, width=int(.095 * w))
        d.rounded_rectangle([cx - .27 * w, by, cx + .27 * w, by + .6 * h], int(.15 * w), fill=white,
                            outline=grey, width=lw)
        d.rounded_rectangle([cx - .15 * w, by + .09 * h, cx + .15 * w, by + .25 * h], int(.04 * w), fill=navy)
        f = _font(max(8, int(.085 * h)), True, False)
        d.text((cx - d.textlength("AI", font=f) / 2, by + .105 * h), "AI", font=f, fill=cyan)
        hy = .30 * h + fy
        d.line([(cx, hy - .2 * h), (cx, hy - .26 * h)], fill=grey, width=lw)
        d.ellipse([cx - .035 * w, hy - .30 * h, cx + .035 * w, hy - .24 * h], fill=cyan)
        for sx in (-1, 1):
            d.ellipse([cx + sx * .41 * w - .05 * w, hy - .05 * h, cx + sx * .41 * w + .05 * w, hy + .05 * h], fill=cyan)
        d.rounded_rectangle([cx - .40 * w, hy - .2 * h, cx + .40 * w, hy + .2 * h], int(.2 * w), fill=white,
                            outline=grey, width=lw)
        d.rounded_rectangle([cx - .32 * w, hy - .14 * h, cx + .32 * w, hy + .14 * h], int(.12 * w), fill=navy)
        blink = (T % 4.1) < 0.12
        for sx in (-1, 1):
            ry = .05 * h * (.2 if blink else 1.0)
            d.ellipse([cx + sx * .14 * w - .06 * w, hy - .03 * h - ry, cx + sx * .14 * w + .06 * w,
                       hy - .03 * h + ry], fill=cyan)
        d.arc([cx - .1 * w, hy - .01 * h, cx + .1 * w, hy + .09 * h], 20, 160, fill=cyan, width=lw)
        L = L.resize((rw, rh), Image.LANCZOS)
        x = W - rw - int(self.m * 0.15)
        y = (H - rh) if (not self.portrait or not self.subtitles) else (H - self.cap_h - rh + int(rh * .40))
        img.paste(L, (x, y), L)

    # ---------- title card ----------
    def intro(self, title, difficulty):
        W, H, pal = self.W, self.H, self.pal
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        m = int(W * .08)
        d.rectangle([0, 0, W, 10], fill=pal["a1"])
        text_box(d, self.label, (m, int(H * .14), W - m, int(H * .34)), BLUE, int(H * .17), 24,
                 True, "center")
        d.rounded_rectangle([W // 2 - int(W * .08), int(H * .365), W // 2 + int(W * .08), int(H * .375)], 5,
                            fill=pal["a2"])
        pw0, pw1 = m, W - m
        d.rounded_rectangle([pw0, int(H * .41), pw1, int(H * .68)], int(H * .13), fill=NAVY, outline=WHITE, width=4)
        text_box(d, title, (pw0 + 40, int(H * .42), pw1 - 40, int(H * .67)), WHITE, int(H * .085), 18, True,
                 "center", self.indic,
                 hl=self._title_hl(title, ""), hl_fill=YELLOW)
        cw, ch = int(W * .30), int(H * .085)
        cx0, cy0 = (W - cw) // 2, int(H * .74)
        d.rounded_rectangle([cx0, cy0, cx0 + cw, cy0 + ch], ch // 2, fill=pal["a1"])
        chip = KIND_CHIP.get(self.kind, f"{difficulty} level")
        text_box(d, chip, (cx0 + 10, cy0 + 2, cx0 + cw - 10, cy0 + ch - 2), INK, int(ch * .55), 10, True)
        ef = _font(max(12, int(H * .03)), True, False)
        d.text(((W - d.textlength("EduVision", font=ef)) / 2, H * .90), "EduVision", font=ef, fill=NAVY)
        return img


def _split_sentences(text):
    s = [x.strip() for x in re.split(r"(?<=[.!?।॥])\s+", text.strip()) if x.strip()]
    return s or [text.strip() or "."]


def _group(sentences, n):
    n = max(1, min(n, len(sentences)))
    size = math.ceil(len(sentences) / n)
    return [" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size)]


def _render_size(aspect):
    W, H = ASPECTS[aspect]
    RW = RENDER_WIDTH if W >= H else int(RENDER_WIDTH * 9 / 16)
    RW -= RW % 2
    RH = int(round(RW * (H / W) / 2.0)) * 2
    return (W, H), (RW, RH)


def render_scene(scene, idx, total, audio, audio_len, out_path, work_dir, ffmpeg, cfg, tempo=1.0, extra_pause=0.0):
    """Draw every frame of one scene and pipe them into FFmpeg together with the voice."""
    (W, H), (RW, RH) = _render_size(cfg["aspect"])
    rend = SceneRenderer((RW, RH), cfg["audience"], cfg["difficulty"], cfg["language"], cfg["style"],
                         cfg["subtitles"], cfg.get("voice", "Female"), cfg.get("kind", "educational"),
                         has_example=bool(scene.get("example")))
    if scene.get("photo"):
        try:
            rend.load_photo(scene["photo"])
        except Exception:
            logger.warning("Could not load photo for scene %s", idx, exc_info=True)
            rend.canvas = None
    steps = _group(_split_sentences(scene["narration"]), len(scene["labels"]))
    weights = [max(1, len(s)) for s in steps]
    eff = audio_len + extra_pause
    durs = [eff * w / sum(weights) for w in weights]
    durs[-1] += PAUSE
    total_len = eff + PAUSE
    fade = min(0.35, total_len / 4)
    scale = f"scale={W}:{H}:flags=lanczos," if (RW, RH) != (W, H) else ""
    tempo_af = f"atempo={tempo:.3f}," if abs(tempo - 1.0) > 0.01 else ""
    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-framerate", str(FPS), "-i", "-",
           "-i", str(audio),
           "-vf", f"{scale}tpad=stop_mode=clone:stop_duration=2,fade=t=in:st=0:d={fade:.2f},"
                  f"fade=t=out:st={total_len - fade:.2f}:d={fade:.2f},format=yuv420p",
           "-af", f"{tempo_af}highpass=f=70,acompressor=threshold=0.14:ratio=2.5:attack=5:release=120,"
                  f"apad=pad_dur={PAUSE + extra_pause:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF, "-threads", "2", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-t", f"{total_len:.3f}",
           "-movflags", "+faststart", str(out_path)]
    log_path = Path(work_dir) / f"ffmpeg_scene_{idx}.log"
    pan = 1 if idx % 2 == 0 else -1
    code = -1
    with open(log_path, "w", encoding="utf-8", errors="ignore") as logf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=logf, stdout=subprocess.DEVNULL)
        try:
            T = 0.0
            n_lab = len(scene["labels"])
            for j, step in enumerate(steps):
                k = n_lab if j == len(steps) - 1 else max(1, math.ceil((j + 1) * n_lab / len(steps)))
                layer = rend.layer(scene, idx - 1, total, step, k, show_ex=(j == len(steps) - 1))
                nframes = max(2, int(round(durs[j] * FPS)))
                for _ in range(nframes):
                    frame = rend.bg.copy()
                    rend.draw_glow(frame, T)
                    if rend.canvas is not None:
                        rend.paste_photo(frame, min(1.0, T / total_len), pan)
                    rend.draw_front(frame, T)
                    frame.paste(layer, (0, 0), layer)
                    proc.stdin.write(frame.tobytes())
                    T += 1.0 / FPS
            proc.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass
            code = proc.wait()
    if code != 0:
        raise RuntimeError("FFmpeg scene failed: " + log_path.read_text(encoding="utf-8", errors="ignore")[-1200:])
    return str(out_path)


def render_intro(title, cfg, out_path, work_dir, ffmpeg):
    (W, H), (RW, RH) = _render_size(cfg["aspect"])
    rend = SceneRenderer((RW, RH), cfg["audience"], cfg["difficulty"], cfg["language"], cfg["style"], False,
                         cfg.get("voice", "Female"), cfg.get("kind", "educational"))
    raw = rend.intro(title, cfg["difficulty"]).tobytes()
    scale = f"scale={W}:{H}:flags=lanczos," if (RW, RH) != (W, H) else ""
    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-framerate", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-vf", f"{scale}fade=t=in:st=0:d=0.4,fade=t=out:st={INTRO_SECONDS - 0.4:.2f}:d=0.4,format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF, "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-t", str(INTRO_SECONDS), str(out_path)]
    log_path = Path(work_dir) / "ffmpeg_intro.log"
    code = -1
    with open(log_path, "w", encoding="utf-8", errors="ignore") as logf:      # log to a file: no pipe can fill up
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=logf, stdout=subprocess.DEVNULL)
        try:
            for _ in range(INTRO_SECONDS * FPS):
                proc.stdin.write(raw)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            code = proc.wait()
    if code != 0:
        raise RuntimeError("FFmpeg intro failed: " + log_path.read_text(encoding="utf-8", errors="ignore")[-600:])


# ==================================================
# 8. QUIZ
# ==================================================
def generate_quiz(script_text, language="English", difficulty="Beginner", count=5):
    """-> list of {question, options[4], correct_index, explanation}. Harder level = harder questions."""
    if not script_text.strip():
        raise ValueError("No script available for the quiz.")
    import random
    prompt = f"""
Create {count} multiple-choice questions that test what a viewer learned from this video script.
Use ONLY facts stated in the script. Include at least two questions that use the real examples from the script.
Level: {difficulty}.
Beginner = basic understanding. Intermediate = concept application. Advanced = analytical / problem solving.
Write in {language}. {LANGUAGE_NOTE[language.lower()]}

LESSON:
{script_text[:9000]}

Rules: exactly 4 options, exactly one correct, plausible wrong answers, a one or two sentence explanation.
Return JSON: {{"questions": [{{"question": "...", "options": ["a","b","c","d"], "correct_index": 0, "explanation": "..."}}]}}
"""
    for _ in range(3):
        data = ask_json(prompt)
        quiz = []
        for q in data.get("questions", []) if isinstance(data.get("questions"), list) else []:
            try:
                opts = [str(o).strip() for o in q["options"]]
                idx = int(q["correct_index"])
                question = str(q["question"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if len(opts) != 4 or len(set(opts)) != 4 or not 0 <= idx <= 3 or not question:
                continue
            correct = opts[idx]
            random.shuffle(opts)
            quiz.append({"question": question, "options": opts, "correct_index": opts.index(correct),
                         "explanation": str(q.get("explanation", "")).strip()})
        if len(quiz) >= 3:
            return quiz[:count]
    raise ValueError("The AI could not create a valid quiz.")


def quiz_from_script_simple(scenes, count=5):
    """Offline quiz (no AI): 'which term matches this definition?'. Works in any language."""
    import random
    items = [(s["key_term"]["term"], s["key_term"]["definition"]) for s in scenes
             if s["key_term"].get("term") and s["key_term"].get("definition")]
    if len(items) < 4:
        return []
    random.shuffle(items)
    quiz = []
    for term, definition in items[:count]:
        wrong = random.sample([t for t, _ in items if t != term], min(3, len(items) - 1))
        if len(wrong) < 3:
            continue
        opts = wrong + [term]
        random.shuffle(opts)
        quiz.append({"question": definition, "options": opts, "correct_index": opts.index(term),
                     "explanation": f"{term}: {definition}"})
    return quiz


# ==================================================
# 8b. HELPERS REQUIRED BY app.py
# ==================================================
def extract_text(path):
    """Text from a .txt / .pdf / image file (images use OCR if pytesseract is installed, else '')."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".txt":
        return p.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        try:
            import pymupdf as fitz
        except ImportError:
            try:
                import fitz
            except ImportError:
                raise ImportError("Reading PDFs needs: pip install PyMuPDF")
        with fitz.open(str(p)) as doc:
            return "\n".join(page.get_text() for page in doc)
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        try:
            import pytesseract
            with Image.open(p) as im:
                return pytesseract.image_to_string(im.convert("RGB"))
        except Exception:
            return ""
    raise ValueError("Unsupported file type. Use PDF, TXT, PNG, JPG or WEBP.")


def indic_status():
    """How Kannada / Hindi letters will be drawn."""
    if indic_text and indic_text.RAQM:
        return "Pillow RAQM"
    if indic_text and indic_text.AVAILABLE:
        return "HarfBuzz (uharfbuzz)"
    return "NOT AVAILABLE (pip install uharfbuzz)"


def ai_status():
    gem = f"Gemini ({GEMINI_MODEL})" if GEMINI_API_KEY else "Gemini off"
    return (f"AI: {gem} | Ollama {OLLAMA_MODEL} (vision: {OLLAMA_VISION_MODEL}) | available={ai_available()} | "
            f"neural voices (edge-tts)={edge_tts_available()} | Kannada/Hindi text: {indic_status()}")


# ==================================================
# 9. FULL PIPELINE
# ==================================================
def _report(progress, pct, msg):
    if progress:
        try:
            progress(pct, msg)
        except Exception:                      # a cancel request is a BaseException and passes through
            logger.debug("progress callback failed", exc_info=True)


def generate_video_package(topic="", audience="School Students", difficulty="", language="English", minutes=3,
                           style="Educational", voice="Female", aspect_ratio="16:9", subtitles=True,
                           source_text="", image_path=None, make_quiz=True, intro_card=True, progress=None,
                           duration_minutes=None, duration="", highlights=True, music=False, **_ignored):
    """
    Returns dict: filename, path, title, kind, audience, difficulty, language, voice, duration_seconds, scene_count,
    script_text, quiz, credits, voice_engine, script_mode, generation_seconds.

    topic may be EMPTY when image_path is given: the picture is analysed and the lesson is made about what it shows.
    Only EDUCATIONAL pictures are accepted; anything else raises ValueError(NOT_EDUCATIONAL_MSG).
    (highlights / music / duration are accepted so app.py can pass them; they are not used.)
    """
    t_start = time.time()
    if duration_minutes:
        minutes = duration_minutes
    topic = re.sub(r"\s+", " ", str(topic or "")).strip()[:300]
    source_text = str(source_text or "").strip()[:12000]
    if image_path and not Path(str(image_path)).is_file():
        image_path = None
    if not topic and not source_text and not image_path:
        raise ValueError("Please enter a topic, provide some text, or upload a picture / file.")
    audience = pick(audience, AUDIENCES, "School Students") if str(audience or "").strip() else "School Students"
    difficulty = pick(difficulty, LEVELS, DEFAULT_LEVEL[audience]) if str(difficulty or "").strip() else DEFAULT_LEVEL[audience]
    language = pick(language, list(LANG_KEYS.values()), "English")
    voice = "Male" if str(voice or "").lower().startswith("m") else "Female"
    style = normalize_style(style)
    if aspect_ratio not in ASPECTS:
        aspect_ratio = "16:9"
    try:
        minutes = max(1.0, min(float(MAX_MINUTES), float(minutes)))
    except (TypeError, ValueError):
        minutes = 3.0

    if voice == "Male" and not edge_tts_available():
        raise ValueError("The male voice needs edge-tts. Run: pip install edge-tts")
    if language.lower() in SCRIPT_RANGES:
        if not _find_font("indic"):
            raise ValueError("No Kannada/Hindi font found. Install 'Nirmala UI' (Windows) or "
                             "Noto Sans Kannada/Devanagari (Linux).")
        if not (indic_text and (indic_text.RAQM or indic_text.AVAILABLE)):
            raise ValueError("Kannada/Hindi letters need the HarfBuzz text engine. Run: pip install uharfbuzz "
                             "and make sure services/indic_text.py exists. Then restart the server.")
    ffmpeg = get_ffmpeg()

    # ---- 0) understand what we were given (picture / text) ----
    kind = "educational"
    typed_topic = "" if _looks_like_filename(topic) else topic      # a file name is never a real topic
    if image_path:
        _report(progress, 3, "Checking your picture")
        info = check_educational_image(image_path)       # ValueError -> "I can't read this file ..."
        kind = "educational"
        topic = typed_topic or info["topic"]
        extra = "\n".join(x for x in (info["description"], info["visible_text"]) if x)
        source_text = (source_text + "\n" + extra).strip()
    elif len(source_text.split()) >= 30:
        kind = classify_text(source_text)
        if kind == "resume" or not typed_topic:
            topic = guess_topic(source_text, kind) or typed_topic
        else:
            topic = typed_topic
    else:
        topic = typed_topic
    if kind == "resume":
        source_text = _scrub_contacts(source_text)                  # never speak phone numbers / e-mails
    source_text = source_text[:12000]
    topic = topic or " ".join(source_text.split()[:6]) or ("Professional Profile" if kind == "resume" else "")
    if not topic:
        raise ValueError("I could not find out what this is about. Please type a topic.")
    topic = topic[:300]
    logger.info("Content kind: %s | topic: %s", kind, topic)

    video_id = uuid.uuid4().hex[:12]
    work = TEMP_DIR / video_id
    work.mkdir(parents=True, exist_ok=True)
    used = set()                                   # photo urls already used in THIS video
    with _tts_lock:
        _tts_stats["fallbacks"] = 0
    portrait = aspect_ratio == "9:16"
    cfg = dict(aspect=aspect_ratio, audience=audience, difficulty=difficulty, language=language, style=style,
               subtitles=bool(subtitles), voice=voice, kind=kind)
    try:
        # ---- 1) script ----
        _report(progress, 5, f"Writing the {difficulty} lesson for {AUDIENCE_TAG[audience]}" if kind in
                ("educational", "general") else "Writing the video script")
        rate, soft = voice_style(audience, difficulty)         # School + Beginner = slow and soft voice
        title, scenes, script_mode = build_script(topic, source_text, audience, difficulty, language, style, minutes,
                                                  kind=kind, progress=lambda f, m: _report(progress, 5 + 20 * f, m),
                                                  rate_pct=rate)
        n = len(scenes)

        # ---- 2) voice + visuals at the same time ----
        _report(progress, 28, "Creating the voice and preparing the visuals")
        audios = [work / f"scene_{i}.mp3" for i in range(1, n + 1)]
        done = [0]
        lock = threading.Lock()

        def tick():
            with lock:
                done[0] += 1
                _report(progress, 28 + 22 * done[0] / (2 * n), "Creating the voice and preparing the visuals")

        def do_voice(k):
            generate_narration(scenes[k]["narration"], audios[k], language, voice, rate, soft)
            tick()

        def do_photo(k):
            sc = scenes[k]
            sc["photo"], sc["photo_source"] = None, ""
            # the user's own (educational) picture is shown in the first scene
            if k == 0 and image_path and kind in ("educational", "general"):
                try:
                    out = work / f"photo_{k + 1}.jpg"
                    with Image.open(image_path) as im:
                        im.convert("RGB").save(out, "JPEG", quality=92)
                    sc["photo"], sc["photo_source"] = str(out), "Upload"
                    return tick()
                except Exception:
                    logger.warning("Uploaded image could not be used", exc_info=True)
            # abstract scenes (software, maths, processes) get a drawn concept card, never a random stock photo
            q = sc["image_query"] if sc.get("visual") == "photo" else ""
            if q:
                words = q.split()
                out = work / f"photo_{k + 1}.jpg"
                if ai_images and ai_images.generate_scene_image(q, sc["title"], topic, str(out), portrait):
                    sc["photo"], sc["photo_source"] = str(out), "AI generated"
                    return tick()
                src = find_photo([q, sc["image_query_alt"], " ".join(words[:3]), " ".join(words[:2])], out,
                                 portrait, used=used)
                if src:
                    sc["photo"], sc["photo_source"] = str(out), src
            tick()

        with ThreadPoolExecutor(max_workers=10) as ex:
            vf = [ex.submit(do_voice, k) for k in range(n)]
            pf = [ex.submit(do_photo, k) for k in range(n)]
            for f in vf:
                f.result()                       # a voice error stops the video
            for f in pf:
                try:
                    f.result(timeout=PHOTO_BUDGET * 4 + 10)
                except Exception:
                    logger.warning("A photo search failed; that scene uses a concept card.", exc_info=True)

        raw = [get_duration(a, ffmpeg) for a in audios]
        if any(x <= 0 for x in raw):
            raise RuntimeError("Could not read the narration length.")

        # ---- 3) fit the requested minutes (voice speed change, then calm pauses) ----
        target = max(10.0, minutes * 60 - n * PAUSE)
        ratio = sum(raw) / target
        top_tempo = 1.03 if soft else 1.2                      # never speed a soft voice back up
        tempo = max(0.85, min(top_tempo, ratio)) if abs(ratio - 1) > 0.05 else 1.0
        lens = [x / tempo for x in raw]
        short = target - sum(lens)
        extra = min(6.0, short / n) if short > max(4.0, 0.03 * target) else 0.0

        # ---- 4) render scenes ----
        _report(progress, 52, f"Drawing and rendering scenes (0/{n})")
        clips = [work / f"clip_{i}.mp4" for i in range(1, n + 1)]
        finished = [0]

        def do_render(k):
            render_scene(scenes[k], k + 1, n, audios[k], lens[k], clips[k], work, ffmpeg, cfg, tempo, extra)
            with lock:
                finished[0] += 1
                _report(progress, 52 + 40 * finished[0] / n, f"Drawing and rendering scenes ({finished[0]}/{n})")

        with ThreadPoolExecutor(max_workers=max(1, min(RENDER_WORKERS, n))) as ex:
            for f in [ex.submit(do_render, k) for k in range(n)]:
                f.result()

        # ---- 5) join ----
        _report(progress, 93, "Putting the video together")
        parts = list(clips)
        if intro_card:
            try:
                intro = work / "intro.mp4"
                render_intro(title, cfg, intro, work, ffmpeg)
                parts = [intro] + clips
            except Exception:
                logger.warning("Title card failed; continuing without it.", exc_info=True)
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", title).strip("_") or "lesson"
        final = GENERATED_DIR / f"{safe[:40]}_{video_id}.mp4"
        lst = work / "list.txt"
        lst.write_text("\n".join(f"file '{_ff(p)}'" for p in parts) + "\n", encoding="utf-8")
        run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(final)], "join")
        seconds = get_duration(final, ffmpeg)
        if not final.exists() or seconds <= 0:
            raise RuntimeError("The final MP4 was not created correctly.")

        # ---- 6) quiz ----
        quiz = []
        script_text = "\n\n".join(
            f"{s['title']}\n{s['narration']}" + (f"\nExample: {s['example']['given']} -> {s['example']['result']}"
                                                  if s.get("example") else "") for s in scenes)
        if make_quiz:
            _report(progress, 97, "Creating the quiz")
            try:
                quiz = generate_quiz(script_text, language, difficulty)
            except Exception as exc:
                logger.warning("AI quiz failed (%s); making a simple quiz from the key terms.", str(exc)[:120])
                quiz = quiz_from_script_simple(scenes)

        engine = "neural" if (edge_tts_available() and not _tts_stats["fallbacks"]) else "gtts-fallback"
        return {
            "filename": final.name, "path": str(final), "title": title, "kind": kind, "audience": audience,
            "difficulty": difficulty, "language": language, "voice": voice, "style": style,
            "aspect_ratio": aspect_ratio, "duration_seconds": int(round(seconds)), "scene_count": n,
            "script_text": script_text,
            "quiz": quiz, "voice_engine": engine, "script_mode": script_mode,
            "credits": sorted({f"Image: {s['photo_source']}" for s in scenes if s.get("photo_source")}),
            "generation_seconds": int(round(time.time() - t_start)),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ==================================================
# 10. OPTIONAL WEB PART (Flask blueprint at /quick/)
#     Only needed if you want the standalone page. app.py does not require it.
# ==================================================
from flask import (Blueprint, Flask, current_app, jsonify, redirect, render_template_string, request,
                   send_from_directory, session, url_for)

generate_bp = Blueprint("quick_generate", __name__, url_prefix="/quick")

QUICK_VIDEO_COST = max(0, int(os.getenv("QUICK_VIDEO_COST", os.getenv("VIDEO_COST", "10"))))
JOB_STALE_SECONDS = 900
JOBS = {}
JOBS_LOCK = threading.RLock()
UPLOAD_EXTS = (".txt", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

NO_CREDITS_MSG = (f"You need {QUICK_VIDEO_COST} credits to generate a video. "
                  "Play a learning game to earn more.")


class JobCancelled(BaseException):
    """Raised inside the worker when the user presses Cancel (BaseException so the generator lets it pass)."""


def _hook(name):
    try:
        return current_app.config.get(name)
    except RuntimeError:
        return None


def _uses_credits():
    return bool(_hook("CHARGE_CREDITS") and _hook("GET_USER_CREDITS"))


def _user_id():
    return session.get("user_id")


def _balance(uid):
    fn = _hook("GET_USER_CREDITS")
    return fn(uid) if (fn and uid) else None


def _refund(app, uid):
    fn = app.config.get("REFUND_CREDITS")
    if fn and uid and QUICK_VIDEO_COST:
        try:
            fn(uid, QUICK_VIDEO_COST)
        except Exception:
            app.logger.exception("Refund failed for user %s", uid)


def _release_charge(job_id):
    """True only the first time -> a refund / final keep can never happen twice."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job and job.get("charged"):
            job["charged"] = False
            return True
    return False


def _active_job(owner):
    now = time.time()
    for jid, job in list(JOBS.items()):
        if job["owner"] != owner or job["status"] not in ("queued", "running"):
            continue
        if now - job["updated"] > JOB_STALE_SECONDS:
            job.update(status="failed", cancelled=True, error="The previous video stopped responding.",
                       finished=now)
            if _release_charge(jid):
                _refund(job["app"], job["uid"])
            continue
        return jid
    return None


def _prune():
    cutoff = time.time() - 3600
    with JOBS_LOCK:
        for jid in [k for k, v in JOBS.items() if v["status"] in ("done", "failed") and v["finished"] < cutoff]:
            JOBS.pop(jid, None)


def _extra_links(video_id):
    """Quiz / tutor pages of your app for this video (only if those routes exist)."""
    links = {}
    if not video_id:
        return links
    for key, endpoint in (("quiz_url", "video_quiz.video_quiz_page"), ("tutor_url", "ai_tutor.tutor_page")):
        try:
            links[key] = url_for(endpoint, video_id=video_id)
        except Exception:
            pass
    return links


def _form_params(form, files):
    topic = (form.get("topic") or "").strip()[:300]
    source = (form.get("source_text") or "").strip()[:12000]
    upload = None
    temp = None
    f = files.get("file")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext not in UPLOAD_EXTS:
            raise ValueError("Supported uploads: PDF, TXT, PNG, JPG, WEBP.")
        up_dir = Path(BASE_DIR) / "uploads"
        up_dir.mkdir(exist_ok=True)
        temp = up_dir / f"{uuid.uuid4().hex}{ext}"
        f.save(str(temp))
        if temp.stat().st_size > 10 * 1024 * 1024:
            temp.unlink(missing_ok=True)
            raise ValueError("The file is larger than 10 MB.")
        try:
            if ext == ".txt":
                source = (source + "\n" + temp.read_text(encoding="utf-8", errors="ignore")).strip()[:12000]
            elif ext == ".pdf":
                source = (source + "\n" + extract_text(temp)).strip()[:12000]
            else:
                upload = str(temp)           # a picture: must be educational (checked right below)
                check_educational_image(upload)   # ValueError -> "I can't read this file ..."
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    if not topic and not source and not upload:
        if temp:
            temp.unlink(missing_ok=True)
        raise ValueError("Enter a topic or upload a picture / PDF / text file.")
    try:
        minutes = int(float(form.get("minutes") or 3))
    except ValueError:
        if temp:
            temp.unlink(missing_ok=True)
        raise ValueError("Video length must be a whole number of minutes.")
    if not 1 <= minutes <= MAX_MINUTES:
        if temp:
            temp.unlink(missing_ok=True)
        raise ValueError(f"Video length must be between 1 and {MAX_MINUTES} minutes.")
    params = dict(
        topic=topic, source_text=source, audience=form.get("audience") or "School Students",
        difficulty=form.get("difficulty") or "", language=form.get("language") or "English",
        minutes=minutes, style=form.get("style") or "Educational", voice=form.get("voice") or "Female",
        aspect_ratio=form.get("aspect_ratio") or "16:9", subtitles=form.get("subtitles", "on") != "off",
        make_quiz=form.get("make_quiz", "on") != "off", image_path=upload)
    return params, [temp] if temp else []


def _worker(app, job_id, uid, params, temps):
    def progress(pct, msg):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is None or job.get("cancelled"):
                raise JobCancelled()
            job.update(status="running", percent=max(job["percent"], min(99, int(pct))), message=str(msg),
                       updated=time.time())

    try:
        res = generate_video_package(progress=progress, **params)
        video_id = None
        save = app.config.get("SAVE_VIDEO_RECORD")
        if save and uid:
            video_id = save(uid, {
                "title": res["title"], "style": res["style"], "language": res["language"],
                "difficulty": res["difficulty"], "audience": res["audience"], "aspect_ratio": res["aspect_ratio"],
                "filename": res["filename"], "duration_seconds": res["duration_seconds"],
                "subtitles": params["subtitles"], "highlights": True, "music": False,
                "script_text": res["script_text"]})
            if not video_id:
                raise RuntimeError("The video was made, but its database record could not be saved.")
            for hook in ("LOG_ACTIVITY", "BUMP_VIDEO_PROGRESS"):
                fn = app.config.get(hook)
                if fn:
                    try:
                        fn(uid, "video") if hook == "LOG_ACTIVITY" else fn(uid)
                    except Exception:
                        app.logger.warning("%s failed", hook, exc_info=True)
        _release_charge(job_id)                                  # success: keep the charge
        m, s = divmod(res["duration_seconds"], 60)
        res["video_id"] = video_id
        res["duration"] = f"{m}m {s:02d}s"
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job and not job.get("cancelled"):
                job.update(status="done", percent=100, message="Your video is ready!", result=res,
                           finished=time.time(), updated=time.time())
    except JobCancelled:
        app.logger.info("Quick video job %s cancelled", job_id)
    except BaseException as exc:
        app.logger.exception("Quick video failed")
        text = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {str(exc)[:300]}"
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job and not job.get("cancelled"):
                job.update(status="failed",
                           error=text + (" Your credits were refunded." if QUICK_VIDEO_COST and uid else ""),
                           finished=time.time())
    finally:
        if _release_charge(job_id):                              # still held -> failed or cancelled
            _refund(app, uid)
        for p in temps:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job and job["status"] in ("queued", "running"):
                job.update(status="failed", error="The job ended unexpectedly.", finished=time.time())


@generate_bp.before_request
def _need_login():
    if _uses_credits() and not _user_id():
        if request.path.rstrip("/").endswith("/quick"):
            return None
        return jsonify(ok=False, error="Your session expired. Please log in again."), 401
    return None


@generate_bp.route("/")
def page():
    uid = _user_id()
    return render_template_string(
        PAGE, audiences=AUDIENCES, levels=LEVELS, languages=list(LANG_KEYS.values()),
        max_minutes=MAX_MINUTES, cost=QUICK_VIDEO_COST if _uses_credits() else 0,
        credits=_balance(uid), logged_in=bool(uid) or not _uses_credits(), ai=ai_available(),
        edge=edge_tts_available())


@generate_bp.route("/start", methods=["POST"])
def start():
    app = current_app._get_current_object()
    uid = _user_id()
    owner = uid or request.remote_addr
    _prune()
    with JOBS_LOCK:
        existing = _active_job(owner)
    if existing:
        return jsonify(ok=True, job_id=existing, resumed=True, credits=_balance(uid))
    try:
        params, temps = _form_params(request.form, request.files)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    charged = False
    if _uses_credits() and QUICK_VIDEO_COST:
        if not app.config["CHARGE_CREDITS"](uid, QUICK_VIDEO_COST):
            for t in temps:
                Path(t).unlink(missing_ok=True)
            # ERROR ONLY: the page shows just this message, no progress bar, no pipeline chips
            return jsonify(ok=False, error=NO_CREDITS_MSG, credits=_balance(uid)), 402
        charged = True
    job_id = uuid.uuid4().hex
    now = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = dict(owner=owner, uid=uid, app=app, status="queued", percent=1, message="Starting",
                            error="", result=None, created=now, updated=now, finished=now,
                            cancelled=False, charged=charged)
    threading.Thread(target=_worker, args=(app, job_id, uid, params, temps), daemon=True).start()
    return jsonify(ok=True, job_id=job_id, credits=_balance(uid))


@generate_bp.route("/status/<job_id>")
def status(job_id):
    uid = _user_id()
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        job = dict(job) if job else None
    if not job or job["owner"] != (uid or request.remote_addr):
        return jsonify(ok=False, error="Job not found."), 404
    out = dict(ok=True, status=job["status"], percent=job["percent"], message=job["message"],
               error=job["error"], credits=_balance(uid))
    if job["status"] == "done" and job["result"]:
        r = job["result"]
        out["result"] = dict(
            video_url=f"/quick/video/{r['filename']}", download_url=f"/quick/video/{r['filename']}?download=1",
            title=r["title"], kind=r.get("kind", "educational"), audience=r["audience"],
            difficulty=r["difficulty"], language=r["language"],
            voice=r["voice"], duration=r["duration"], scenes=r["scene_count"], quiz=r["quiz"],
            voice_engine=r["voice_engine"], script_mode=r["script_mode"], credits_text=r["credits"],
            seconds=r["generation_seconds"], **_extra_links(r.get("video_id")))
    return jsonify(out)


@generate_bp.route("/cancel", methods=["POST"])
def cancel():
    uid = _user_id()
    owner = uid or request.remote_addr
    app = current_app._get_current_object()
    with JOBS_LOCK:
        ids = [j for j, v in JOBS.items() if v["owner"] == owner and v["status"] in ("queued", "running")]
        for j in ids:
            JOBS[j].update(status="failed", cancelled=True, error="Cancelled.", finished=time.time())
    for j in ids:
        if _release_charge(j):
            _refund(app, uid)
    return jsonify(ok=True, credits=_balance(uid))


@generate_bp.route("/video/<path:filename>")
def video(filename):
    name = Path(filename).name
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.mp4", name):
        return jsonify(ok=False, error="Not found."), 404
    return send_from_directory(str(GENERATED_DIR), name, as_attachment=request.args.get("download") == "1",
                               download_name=name)


# The progress card (bar) is hidden until the server ACCEPTS the job. Errors use their own card and hide everything else.
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Quick Video Generator | EduVision</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f1f4fb;color:#182033}
.wrap{max-width:1000px;margin:0 auto;padding:24px 16px 60px}h1{margin:0 0 4px;font-size:28px}
.sub{color:#5c6475;margin:0 0 20px}.card{background:#fff;border-radius:18px;padding:22px;box-shadow:0 10px 34px #1820331a;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}
label{display:block;font-weight:600;font-size:14px;margin:0 0 6px}
input,select,textarea{width:100%;padding:11px;border:1px solid #d7dce7;border-radius:10px;font-size:15px;font-family:inherit}
textarea{min-height:80px;resize:vertical}.full{grid-column:1/-1}
button{border:0;border-radius:10px;padding:13px 22px;font-size:16px;font-weight:700;cursor:pointer;background:#5546e8;color:#fff}
button.sec{background:#e9e7ff;color:#3b2fc0}button:disabled{opacity:.55;cursor:not-allowed}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:16px}
.bar{height:16px;background:#e5e8f2;border-radius:99px;overflow:hidden}.bar>div{height:100%;width:0;background:linear-gradient(90deg,#5546e8,#22c3a6);transition:width .4s}
.msg{margin:10px 0 0;color:#5c6475}
.errcard{border-left:6px solid #c0262d;background:#fff5f5}
.errcard p{margin:0;color:#c0262d;font-weight:600;font-size:16px;line-height:1.5}
.warn{background:#fff6e0;border-radius:10px;padding:10px;color:#7a5a00;margin-bottom:14px;font-size:14px}
video{width:100%;border-radius:14px;background:#000}.tags span{display:inline-block;background:#eef0ff;color:#3b2fc0;border-radius:99px;padding:4px 12px;margin:4px 6px 0 0;font-size:13px;font-weight:600}
.q{border:1px solid #e3e6f0;border-radius:12px;padding:14px;margin:12px 0}.q p{margin:0 0 10px;font-weight:600}
.opt{display:block;width:100%;text-align:left;background:#f6f7fb;color:#182033;margin:6px 0;font-weight:500}
.opt.ok{background:#d9f5e5;color:#0b6b3a}.opt.bad{background:#fde1e1;color:#9b1c1c}.exp{font-size:14px;color:#3d4660;margin-top:8px}
.hidden{display:none}small{color:#6b7385}a.lnk{color:#5546e8;font-weight:600;text-decoration:none;margin-right:14px}
</style></head><body><div class="wrap">
<h1>Quick Video Generator</h1><p class="sub">Topic, text or an educational picture &rarr; script &rarr; voice &rarr; visuals &rarr; animated MP4 &rarr; quiz</p>
{% if not logged_in %}<div class="warn">Please log in first.</div>{% endif %}
{% if not edge %}<div class="warn">edge-tts is not installed: the male voice is unavailable and the female voice is basic. Run <b>pip install edge-tts</b>.</div>{% endif %}
{% if not ai %}<div class="warn">No AI model detected (set GEMINI_API_KEY or start Ollama). Videos will be built from Wikipedia / your pasted text instead (without worked examples), and pictures can only be read with OCR.</div>{% endif %}
<form id="f" class="card"><div class="grid">
<div class="full"><label>Topic <small>(optional when you upload an educational picture or file)</small></label><input name="topic" placeholder="e.g. What is a Neural Network?"></div>
<div><label>Audience</label><select name="audience">{% for a in audiences %}<option>{{a}}</option>{% endfor %}</select></div>
<div><label>Level</label><select name="difficulty"><option value="">Automatic</option>{% for l in levels %}<option>{{l}}</option>{% endfor %}</select></div>
<div><label>Language</label><select name="language">{% for l in languages %}<option>{{l}}</option>{% endfor %}</select></div>
<div><label>Voice</label><select name="voice"><option>Female</option><option>Male</option></select></div>
<div><label>Length (minutes, 1-{{max_minutes}})</label><input type="number" name="minutes" min="1" max="{{max_minutes}}" value="2"></div>
<div><label>Style</label><select name="style"><option>Educational</option><option>Storytelling</option><option>Simple Explanation</option><option>Presenter</option></select></div>
<div><label>Screen</label><select name="aspect_ratio"><option value="16:9">Landscape 16:9</option><option value="9:16">Phone 9:16</option></select></div>
<div><label>Captions</label><select name="subtitles"><option value="on">On</option><option value="off">Off</option></select></div>
<div><label>Quiz at the end</label><select name="make_quiz"><option value="on">Yes</option><option value="off">No</option></select></div>
<div><label>Upload (picture / PDF / TXT)</label><input type="file" name="file" accept=".pdf,.txt,.png,.jpg,.jpeg,.webp,.bmp"><small>A picture must be educational (diagram, chart, map, textbook or notes page). Other pictures are refused.</small></div>
<div class="full"><label>Or paste your own text (optional)</label><textarea name="source_text" placeholder="The video will teach from this text"></textarea></div>
</div>
<div class="row"><button id="go" type="submit">Generate video{% if cost %} ({{cost}} credits){% endif %}</button>
<button id="stop" type="button" class="sec hidden">Cancel</button>
{% if credits is not none %}<small>Credits: <b id="cr">{{credits}}</b></small>{% endif %}</div></form>

<!-- ERROR ONLY: just the message, no progress bar and no pipeline -->
<div id="errbox" class="card errcard hidden"><p id="em"></p></div>

<!-- PROGRESS: shown only after the server has accepted the job -->
<div id="prog" class="card hidden"><div class="bar"><div id="pb"></div></div><p class="msg" id="pm">Starting...</p></div>

<div id="out" class="card hidden"><h2 id="vt"></h2><div class="tags" id="tags"></div><br>
<video id="vp" controls></video><div class="row"><a id="dl"><button type="button" class="sec">Download MP4</button></a>
<span id="links"></span></div>
<small id="cred"></small></div>
<div id="quiz" class="card hidden"><h2>Knowledge check</h2><div id="qs"></div><p id="score"></p></div>
</div>
<script>
const $=id=>document.getElementById(id);let job=null,timer=null;
function setBusy(b){$('go').disabled=b;$('stop').classList.toggle('hidden',!b)}
function hideAll(){['errbox','prog','out','quiz'].forEach(i=>$(i).classList.add('hidden'))}
function fail(t){                      // error only: progress bar and pipeline are hidden completely
 clearInterval(timer);setBusy(false);
 $('prog').classList.add('hidden');$('out').classList.add('hidden');$('quiz').classList.add('hidden');
 $('em').textContent=t||'Something went wrong.';$('errbox').classList.remove('hidden');
 $('errbox').scrollIntoView({behavior:'smooth',block:'nearest'})}
$('f').addEventListener('submit',async e=>{e.preventDefault();
 hideAll();setBusy(true);                               // nothing is shown until the server answers
 try{const r=await fetch('/quick/start',{method:'POST',body:new FormData($('f'))});const d=await r.json();
  if(d.credits!=null&&$('cr'))$('cr').textContent=d.credits;
  if(!d.ok){return fail(d.error||'Could not start.')}   // e.g. "You need 10 credits ..." -> message only
  $('pm').textContent='Starting...';$('pb').style.width='1%';$('prog').classList.remove('hidden');
  job=d.job_id;timer=setInterval(poll,2000);poll();
 }catch(x){fail('Network error: '+x)}});
$('stop').onclick=async()=>{clearInterval(timer);
 try{const r=await fetch('/quick/cancel',{method:'POST'});const d=await r.json();
  if(d.credits!=null&&$('cr'))$('cr').textContent=d.credits}catch(x){}
 fail('Cancelled. Your credits were refunded.')};
async function poll(){try{const r=await fetch('/quick/status/'+job);const d=await r.json();
 if(!d.ok)return fail(d.error);
 if(d.credits!=null&&$('cr'))$('cr').textContent=d.credits;
 if(d.status==='failed')return fail(d.error||'Failed.');
 $('pb').style.width=d.percent+'%';$('pm').textContent=d.message+' ('+d.percent+'%)';
 if(d.status==='done'){clearInterval(timer);setBusy(false);$('prog').classList.add('hidden');show(d.result)}}catch(x){}}
function show(r){$('out').classList.remove('hidden');$('vt').textContent=r.title;
 const kinds={resume:'Profile video',document:'Document summary',general:'Explainer',educational:'Lesson'};
 $('tags').innerHTML=[kinds[r.kind]||'Lesson',r.audience,r.difficulty,r.language,r.voice+' voice',r.duration,r.scenes+' scenes','made in '+r.seconds+'s'].map(t=>'<span>'+t+'</span>').join('');
 $('vp').src=r.video_url;$('dl').href=r.download_url;$('cred').textContent=(r.credits_text||[]).join('  |  ');
 let l='';if(r.quiz_url)l+='<a class="lnk" href="'+r.quiz_url+'">Full quiz page</a>';
 if(r.tutor_url)l+='<a class="lnk" href="'+r.tutor_url+'">Ask the AI tutor</a>';
 l+='<a class="lnk" href="/dashboard#my-videos">My videos</a>';$('links').innerHTML=l;
 if(r.quiz&&r.quiz.length){$('quiz').classList.remove('hidden');let right=0,done=0;$('qs').innerHTML='';$('score').textContent='';
  r.quiz.forEach((q,qi)=>{const d=document.createElement('div');d.className='q';const p=document.createElement('p');p.textContent=(qi+1)+'. '+q.question;d.appendChild(p);
   q.options.forEach((o,oi)=>{const b=document.createElement('button');b.type='button';b.className='opt';b.textContent=o;
    b.onclick=()=>{if(d.dataset.done)return;d.dataset.done=1;done++;const bs=d.querySelectorAll('.opt');
     bs[q.correct_index].classList.add('ok');if(oi===q.correct_index)right++;else b.classList.add('bad');
     const e=document.createElement('div');e.className='exp';e.textContent=q.explanation||'';d.appendChild(e);
     if(done===r.quiz.length)$('score').textContent='Score: '+right+' / '+r.quiz.length};d.appendChild(b)});
   $('qs').appendChild(d)})}}
</script></body></html>"""


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
    app.register_blueprint(generate_bp)

    @app.route("/")
    def home():
        return redirect("/quick/")

    return app


def _cli():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Generate a video from a topic, a text file or an educational picture")
    ap.add_argument("topic", nargs="?", default="", help="optional when --image is given")
    ap.add_argument("--image", default=None, help="educational picture to explain (diagram, chart, map, notes page ...)")
    ap.add_argument("--audience", default="School Students", choices=AUDIENCES)
    ap.add_argument("--level", default="", choices=[""] + LEVELS)
    ap.add_argument("--language", default="English", choices=list(LANG_KEYS.values()))
    ap.add_argument("--minutes", type=float, default=2)
    ap.add_argument("--voice", default="Female", choices=["Female", "Male"])
    ap.add_argument("--style", default="Educational")
    ap.add_argument("--aspect", default="16:9", choices=list(ASPECTS))
    a = ap.parse_args()
    if not a.topic and not a.image:
        ap.error("give a topic or --image")
    res = generate_video_package(a.topic, a.audience, a.level, a.language, a.minutes, a.style, a.voice, a.aspect,
                                 image_path=a.image, progress=lambda p, m: print(f"[{p:5.1f}%] {m}"))
    print("\nDONE:", res["path"], f"({res['duration_seconds']}s, {res['scene_count']} scenes, kind={res['kind']}, "
          f"voice={res['voice_engine']})")
    for i, q in enumerate(res["quiz"], 1):
        print(f"Q{i}. {q['question']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _cli()                                   # python video_generator.py "Topic" --voice Male ...
    else:
        print("Quick Video Generator: http://127.0.0.1:5001/quick/")
        print("AI available:", ai_available(), "| neural voices (edge-tts):", edge_tts_available())
        print("Kannada/Hindi text:", indic_status())
        create_app().run(host="127.0.0.1", port=5001, debug=False, use_reloader=False, threaded=True)
