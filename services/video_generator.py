"""
EduVision video generation service  (services/video_generator.py)  -- VISUAL TEACHER VERSION 3 (FAST BUILD)

What changed in this FAST build (same features, much shorter waiting time)
  * Rendering is lighter: 10 frames per second (was 15), smaller render size (800x450, FFmpeg scales it up),
    fewer background particles, and the photo zoom uses one single resize call per frame.
  * Fewer AI calls: 45 seconds per scene (was 32), 4 scenes written per call (was 3), only ONE attempt to
    lengthen a short narration (was 2), and a smaller Ollama context window.
  * The voice is no longer recorded twice unless it is more than 25% away from the requested length.
  * The slow vision check on downloaded photos is OFF unless you set EDUVISION_VISION_CHECK=1.
  * Shorter network time-outs for photo sites, so one slow site cannot hold a scene back.
  * Timing log: after each video the log shows how many seconds script / voice+photos / render / join took,
    so you can see the real bottleneck.

Install once:   pip install edge-tts

Optional environment variables (.env)
  GEMINI_API_KEY=xxxx                use Google Gemini (fast, hosted) for the script and quiz
  GEMINI_MODEL=gemini-2.5-flash      change if Google renames the model
  GEMINI_MIN_INTERVAL=4              seconds between Gemini calls (free tier limit)
  OLLAMA_URL, OLLAMA_MODEL           (local AI: used when no Gemini key, or if Gemini fails)
  OLLAMA_NUM_CTX=6144                Ollama context window (smaller = faster)
  OLLAMA_VISION_MODEL=llava          describe uploaded images (leave empty to skip)
  EDUVISION_VISION_CHECK=0           1 = also check every downloaded photo with the vision model (SLOW)
  PEXELS_API_KEY=xxxx                best realistic photos (free key from pexels.com/api)
  PIXABAY_API_KEY=xxxx               more real photos (free key from pixabay.com/api/docs)
  EDUVISION_WEB_IMAGES=0             disable internet photos (diagram-only mode, fastest)
  MAX_VIDEO_MINUTES=600              longest video a user may request
  MUSIC_VOLUME=0.35                  background music loudness (0.05 quiet ... 0.6 loud)
  SECONDS_PER_SCENE=45               longer = fewer scenes = faster
  SCENES_PER_CALL=4                  scenes written by the AI in one call
  ANIM_FPS=10                        frames per second while drawing (8 = faster, 15 = smoother)
  RENDER_WORKERS=                    number of parallel render processes (default: CPU cores - 1, max 6)
  RERECORD_TOLERANCE=0.25            re-record the voice only if its length is off by more than this
  VOICE_EN_FEMALE / VOICE_EN_MALE    force a specific edge-tts voice name (see: edge-tts --list-voices)
  VOICE_BASE_RATE=-3                 base speaking speed in percent (negative = calmer)

IMPORTANT (Windows): your app.py must start Flask with
    if __name__ == "__main__":
        app.run(..., use_reloader=False)
"""
import io
import os
import re
import json
import uuid
import math
import time
import wave
import base64
import random
import shutil
import asyncio
import logging
import threading
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from array import array
from functools import lru_cache
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter
from gtts import gTTS

# ==================================================
# 1. CONFIGURATION
# ==================================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)
logger = logging.getLogger(__name__)


def _env_int(name, default, low=None):
    try:
        value = int(float(os.getenv(name, str(default)) or default))
    except ValueError:
        value = default
    return max(low, value) if low is not None else value


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)) or default)
    except ValueError:
        return default


GENERATED_DIR = BASE_DIR / "static" / "generated"
TEMP_DIR = GENERATED_DIR / "temp"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

MUSIC_FILE = BASE_DIR / "static" / "music" / "background.mp3"          # your own track (optional)
GENERATED_MUSIC_FILE = BASE_DIR / "static" / "music" / "eduvision_calm.wav"  # built automatically

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "").strip()
OLLAMA_NUM_CTX = _env_int("OLLAMA_NUM_CTX", 6144, 2048)
# Google Gemini (hosted AI, runs on Google's GPUs). If GEMINI_API_KEY is set it is used for all script/quiz
# writing and the local Ollama model is only a fallback.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_MIN_INTERVAL = _env_float("GEMINI_MIN_INTERVAL", 4.0)   # seconds between calls (free tier rate limit)
VISION_CHECK = os.getenv("EDUVISION_VISION_CHECK", "0") == "1"      # slow: off by default
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
USE_WEB_IMAGES = os.getenv("EDUVISION_WEB_IMAGES", "1") != "0"
USER_AGENT = "EduVision/1.0 (educational project; contact: local-install)"

MAX_VIDEO_MINUTES = _env_int("MAX_VIDEO_MINUTES", 600, 1)
DEFAULT_MINUTES = 3
SECONDS_PER_SCENE = _env_int("SECONDS_PER_SCENE", 45, 15)
SCENES_PER_CALL = _env_int("SCENES_PER_CALL", 4, 1)
OUTLINE_CHUNK = 20
MAX_SCENES = int(MAX_VIDEO_MINUTES * 60 / SECONDS_PER_SCENE) + 10
MAX_SOURCE_CHARS = 18000
MUSIC_VOLUME = _env_float("MUSIC_VOLUME", 0.35)
VOICE_BASE_RATE = _env_int("VOICE_BASE_RATE", -3)
RERECORD_TOLERANCE = max(0.06, _env_float("RERECORD_TOLERANCE", 0.25))
PAUSE = 0.8
MAX_EXTRA_PAUSE = 6.0          # longest calm pause added to one scene to reach the requested length
ANIM_FPS = _env_int("ANIM_FPS", 10, 5)
HTTP_TIMEOUT = 12              # seconds for photo-site searches (was 25)
DOWNLOAD_TIMEOUT = 20          # seconds for one photo download (was 40)

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280)}
RENDER_SIZES = {"16:9": (800, 450), "9:16": (450, 800)}   # drawn small, FFmpeg scales to ASPECTS

MAX_WORKERS = max(1, min(_env_int("RENDER_WORKERS", (os.cpu_count() or 2) - 1, 1), 6))
TTS_WORKERS = 4

# how many spoken words fit in one minute (used to plan the script length)
WORDS_PER_MINUTE = {"english": 150, "kannada": 115, "hindi": 135}

STYLE_GUIDE = {
    "Educational": ("Teach like a classroom teacher using a big screen. Introduce with a real-world example, "
                    "explain each part with its own picture, show how it works in real life, end with a recap."),
    "Animated": ("Teach VISUALLY so anyone understands by SEEING. Start with a curious hook question. "
                 "Explain each idea with a simple everyday analogy. Talk about the labels in the "
                 "same order they appear on screen ('First you see...', 'Next...', 'Then...', "
                 "'Finally...'). End with a one-sentence recap."),
    "Simple Explanation": "Use everyday examples, simple comparisons and very short sentences.",
    "Storytelling": ("Explain through one short story with two characters, a problem and a conclusion. "
                     "Each scene is one story beat that quietly teaches the concept."),
}
AUDIENCE_GUIDE = {
    "Kids": "Use very simple words, short sentences, fun examples and a friendly tone.",
    "School Students": "Explain step by step with definitions and school-level examples.",
    "College Students": "Use detailed explanations, technical terms and real-world applications.",
    "Teachers": "Include learning objectives, classroom examples and teaching tips.",
}
DIFFICULTY_GUIDE = {
    "Beginner": "Assume no prior knowledge. Keep it very simple.",
    "Intermediate": "Assume basic school-level knowledge.",
    "Advanced": "Assume strong background knowledge and go deeper.",
}

LANGUAGE_CODES = {"english": "en", "kannada": "kn", "hindi": "hi"}

# Unicode block of each non-English language: used to check that the AI really wrote in that script
SCRIPT_RANGES = {"kannada": (0x0C80, 0x0CFF), "hindi": (0x0900, 0x097F)}
LANGUAGE_NOTE = {
    "english": "Write everything in clear English.",
    "kannada": ("Write everything in Kannada using Kannada script (ಕನ್ನಡ ಲಿಪಿ). Do NOT write Kannada words in "
                "English letters and do NOT answer in English. Use natural spoken Kannada, the way a teacher "
                "talks in class."),
    "hindi": ("Write everything in Hindi using Devanagari script (देवनागरी). Do NOT write Hindi words in English "
              "letters (no Hinglish) and do NOT answer in English. Use simple spoken Hindi, the way a teacher "
              "talks in class."),
}
# label shown on the "real-life example" photo
EXAMPLE_LABEL = {"english": "Real-life example", "kannada": "ನಿಜ ಜೀವನದ ಉದಾಹರಣೆ",
                 "hindi": "वास्तविक जीवन का उदाहरण"}


def _env_voice(name, defaults):
    forced = os.getenv(name, "").strip()
    return ([forced] if forced else []) + list(defaults)


# Microsoft neural voices (edge-tts). The first name that works is used, the others are fallbacks.
# List all voices with:  edge-tts --list-voices
VOICES = {
    "english": {
        "female": _env_voice("VOICE_EN_FEMALE", ["en-US-AvaMultilingualNeural", "en-US-JennyNeural",
                                                  "en-IN-NeerjaNeural"]),
        "male": _env_voice("VOICE_EN_MALE", ["en-US-AndrewMultilingualNeural", "en-US-GuyNeural",
                                              "en-IN-PrabhatNeural"]),
    },
    "kannada": {
        "female": _env_voice("VOICE_KN_FEMALE", ["kn-IN-SapnaNeural"]),
        "male": _env_voice("VOICE_KN_MALE", ["kn-IN-GaganNeural"]),
    },
    "hindi": {
        "female": _env_voice("VOICE_HI_FEMALE", ["hi-IN-SwaraNeural"]),
        "male": _env_voice("VOICE_HI_MALE", ["hi-IN-MadhurNeural"]),
    },
}

VISUAL_TYPES = {"flow", "list", "hub", "compare", "story"}
DEFAULT_VISUALS = {
    "Animated": ["flow", "hub", "compare", "list"],
    "Simple Explanation": ["list", "flow"],
    "Storytelling": ["story"],
    "Educational": ["list", "flow", "compare"],
}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")


def normalize_style(style):
    """Accept any dropdown text, e.g. 'Animated Visuals (images & diagrams)' -> 'Animated'."""
    s = str(style or "").strip().lower()
    if "anim" in s or "visual" in s or "diagram" in s:
        return "Animated"
    if "story" in s:
        return "Storytelling"
    if "simple" in s or "easy" in s:
        return "Simple Explanation"
    if "educ" in s or "structur" in s or "lesson" in s:
        return "Educational"
    return "Educational"


def pick(value, valid, default):
    """Case-insensitive choice from `valid`; empty or unknown values give `default`."""
    text = str(value or "").strip().lower()
    for item in valid:
        if text == str(item).lower():
            return item
    return default


def resolve_minutes(duration=None, duration_minutes=None):
    """Minutes the user wants. A typed number wins; Short/Medium/Long are still understood."""
    minutes = None
    if duration_minutes not in (None, ""):
        try:
            minutes = float(duration_minutes)
        except (TypeError, ValueError):
            minutes = None
    if minutes is None:
        minutes = {"short": 1, "medium": 3, "long": 6}.get(str(duration or "").strip().lower(), DEFAULT_MINUTES)
    return max(1.0, min(float(MAX_VIDEO_MINUTES), minutes))


def plan_length(minutes, language):
    """-> (number of scenes, words of narration per scene) for the requested length."""
    total = max(30.0, float(minutes) * 60.0)
    scenes = max(4, min(MAX_SCENES, int(round(total / SECONDS_PER_SCENE))))
    speech_seconds = max(20.0, total - scenes * PAUSE)
    wpm = WORDS_PER_MINUTE.get(str(language).strip().lower(), 140)
    words = max(28, int(speech_seconds / 60.0 * wpm / scenes))
    return scenes, words


# ==================================================
# 2. OLLAMA
# ==================================================
def check_ollama_connection():
    if GEMINI_API_KEY:          # Gemini is the main engine: no local model needed
        return True
    tags_url = OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags"
    try:
        with urllib.request.urlopen(urllib.request.Request(tags_url), timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        if not any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL for n in names):
            raise RuntimeError(f"Model {OLLAMA_MODEL} is not downloaded. Run: ollama pull {OLLAMA_MODEL}")
        return True
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. Make sure Ollama is installed and running. "
            f"Details: {exc}"
        ) from exc


_SYSTEM_PROMPT = ("You are an expert teacher and educational video director. Create accurate, simple and "
                  "engaging content for students. Always return valid JSON only.")
_gemini_lock = threading.Lock()
_gemini_last = [0.0]


def _gemini_response(prompt, temperature=0.4, num_predict=4500):
    """Ask Google Gemini for a JSON answer. Waits and retries on rate limits."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    gen_cfg = {"temperature": temperature,
               "maxOutputTokens": min(8192, max(2048, int(num_predict) * 2)),
               "responseMimeType": "application/json"}
    if "2.5" in GEMINI_MODEL:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}      # no hidden "thinking": faster, cheaper
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }).encode("utf-8")
    last = None
    for attempt in range(4):
        with _gemini_lock:                                      # keep under the free-tier calls per minute
            wait = GEMINI_MIN_INTERVAL - (time.time() - _gemini_last[0])
            if wait > 0:
                time.sleep(wait)
            _gemini_last[0] = time.time()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")[:300]
            last = RuntimeError(f"Gemini HTTP error {exc.code}: {details}")
            if exc.code in (429, 500, 503) and attempt < 3:
                time.sleep(8 * (attempt + 1))
                continue
            raise last from exc
        except Exception as exc:
            last = RuntimeError(f"Gemini request failed: {exc}")
            if attempt < 3:
                time.sleep(3)
                continue
            raise last from exc
        parts = ((result.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(str(p.get("text", "")) for p in parts).strip()
        if text:
            return text
        last = ValueError("Gemini returned an empty answer (blocked or cut off).")
    raise last or RuntimeError("Gemini did not answer.")


def generate_ollama_response(prompt, temperature=0.4, num_predict=4500):
    """Main text-AI call used everywhere. Gemini when GEMINI_API_KEY is set, otherwise (or if Gemini
    fails) the local Ollama model. The name is kept so other files that import it keep working."""
    if GEMINI_API_KEY:
        try:
            return _gemini_response(prompt, temperature, num_predict)
        except Exception as exc:
            logger.warning("Gemini failed (%s). Trying the local Ollama model instead.", exc)
            try:
                return _ollama_response(prompt, temperature, num_predict)
            except Exception as exc2:
                raise RuntimeError(f"Gemini failed: {exc}. Local Ollama also failed: {exc2}") from exc2
    return _ollama_response(prompt, temperature, num_predict)


def _ollama_response(prompt, temperature=0.4, num_predict=4500):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "format": "json",
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Ollama returned an empty response.")
        return content
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama HTTP error {exc.code}: {details}") from exc
    except Exception as exc:
        logger.exception("Ollama response generation failed.")
        raise RuntimeError(f"Ollama generation failed: {exc}") from exc


def parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def ask_json(prompt, attempts=2, num_predict=4500):
    last = None
    for _ in range(attempts):
        try:
            result = parse_json(generate_ollama_response(prompt, num_predict=num_predict))
            if isinstance(result, dict):
                return result
        except Exception as exc:
            last = exc
            logger.warning("Ollama JSON attempt failed: %s", exc)
    raise ValueError(f"Ollama did not return valid JSON. Please try again. ({last})")


def _vision_ask(image_path, prompt, timeout=300):
    """Ask the local vision model (e.g. llava) about a picture. Returns '' if unavailable."""
    if not OLLAMA_VISION_MODEL:
        return ""
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((768, 768))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        payload = {
            "model": OLLAMA_VISION_MODEL, "stream": False, "keep_alive": "10m",
            "messages": [{"role": "user", "images": [b64], "content": prompt}],
        }
        req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("message", {}).get("content", "").strip()
    except Exception:
        logger.warning("Vision request failed.", exc_info=True)
        return ""


def describe_image(image_path):
    """Describe an uploaded picture for the lesson. Returns '' if no vision model is set."""
    return _vision_ask(
        image_path,
        "Describe this picture for a teacher: list the main objects, people, structures or "
        "processes you can see and what concept it teaches. Be factual, 5 sentences max.")


def image_matches(image_path, query):
    """True if the photo really shows `query`. Only checked when EDUVISION_VISION_CHECK=1 (slow)."""
    if not VISION_CHECK or not OLLAMA_VISION_MODEL or not query:
        return True
    answer = _vision_ask(image_path, f'Does this photo clearly show "{query}"? '
                                     'Answer with one word: YES or NO.', timeout=120)
    if not answer:
        return True
    return answer.strip().lower().startswith("yes")


# ==================================================
# 3. SCENES (outline -> batches of detailed teacher scenes)
# ==================================================
def suggest_scene_range(text):
    words = len(text.split())
    if words < 60:
        return 5, 6
    if words < 400:
        return 6, 8
    return 7, 9


def _excerpt(text, index, total, size):
    """A slice of the source that moves along with the scene number, so long PDFs are covered fully."""
    text = text or ""
    if len(text) <= size:
        return text
    start = int((len(text) - size) * (index / max(1, total - 1)))
    return text[start:start + size]


def _tidy(value):
    """Plain text for narration: no Markdown, no bullet marks, single spaces."""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    text = re.sub(r"[*#_`>\[\]]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _clean_query(value):
    return re.sub(r"[\"'\n\r]", " ", str(value or "")).strip()[:60]


def _clean_scene(sc, style, story, position, section):
    if not isinstance(sc, dict):
        return None
    title = str(sc.get("title") or section.get("title") or "").strip()
    explanation = _tidy(sc.get("explanation"))
    example = _tidy(sc.get("example"))
    narration = _tidy(sc.get("narration"))
    example_fraction = 0.6
    if explanation and example:
        narration = f"{explanation} {example}"
        example_fraction = max(0.3, min(0.8, len(explanation) / max(1, len(narration))))
    elif not narration:
        narration = explanation or example
    if not title or not narration:
        return None
    bullets = [str(b).strip() for b in (sc.get("bullets") or []) if str(b).strip()][:4]
    terms = []
    for kt in (sc.get("key_terms") or []):
        if isinstance(kt, dict) and str(kt.get("term", "")).strip():
            terms.append({"term": str(kt["term"]).strip(),
                          "definition": str(kt.get("definition", "")).strip()})
    vtype = str(sc.get("visual_type", "")).strip().lower()
    if story:
        vtype = "story"
    elif vtype not in VISUAL_TYPES or vtype == "story":
        opts = DEFAULT_VISUALS.get(style, ["list"])
        vtype = opts[position % len(opts)]
    raw_items = sc.get("visual_items") or bullets
    items = [str(x).strip()[:40] for x in raw_items if str(x).strip()][:5]
    if len(items) < 2:
        items = [s.strip()[:36] for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()][:4]
    if len(items) < 2:
        items = (items + [title, "Example"])[:2]
    query = _clean_query(sc.get("image_query") or section.get("image_query"))
    alt = _clean_query(sc.get("image_query_alt"))
    ex_query = _clean_query(sc.get("example_query"))
    ex_label = str(sc.get("example_label") or "").strip()[:40]
    return {
        "title": title, "narration": narration, "bullets": bullets,
        "visual_description": str(sc.get("visual_description", "")).strip(),
        "key_terms": terms[:2],
        "visual_type": vtype, "visual_items": items,
        "image_query": "" if story else query,
        "image_query_alt": "" if story else alt,
        "example_query": "" if story else ex_query,
        "example_label": "" if story else ex_label,
        "example_fraction": example_fraction,
    }


def _style_block(style, difficulty, audience, language):
    return (f"VIDEO STYLE: {style}. {STYLE_GUIDE.get(style, '')}\n"
            f"DIFFICULTY: {difficulty}. {DIFFICULTY_GUIDE.get(difficulty, '')}\n"
            f"TARGET AUDIENCE: {audience}. {AUDIENCE_GUIDE.get(audience, '')}\n"
            f"LANGUAGE: {language}. {LANGUAGE_NOTE.get(str(language).strip().lower(), '')}")


def plan_outline(source_text, style, difficulty, language, audience, n, story, progress=None):
    """Ask for the sections of the video, a few at a time, until we have `n` of them."""
    title, sections, seen, empty_rounds = "", [], set(), 0
    for _ in range(n // OUTLINE_CHUNK + 10):
        if len(sections) >= n or empty_rounds >= 2:
            break
        start = len(sections)
        count = min(OUTLINE_CHUNK, n - start)
        final = start + count >= n
        already = "; ".join(s["title"] for s in sections[-40:]) or "none yet"
        story_note = ("The video is ONE short story told in beats: each section is one story beat "
                      "that quietly teaches the concept.\n" if story else "")
        last_note = ("The very last section must be a short recap of the important points.\n"
                     if final else "Do NOT write the recap yet; more sections will follow.\n")
        prompt = f"""
You are an expert teacher planning a classroom video about the content below.
Plan sections {start + 1} to {start + count} of {n} (the whole video has {n} sections).

SOURCE CONTENT:
{_excerpt(source_text, start, n, 6000)}

{_style_block(style, difficulty, audience, language)}
SECTIONS ALREADY PLANNED (do not repeat them): {already}

Order of the whole video:
 section 1  = a familiar real-world example or hook (something students see in daily life)
 section 2  = what the topic is, shown with one clear picture
 middle     = one important part, step or idea per section, each tied to a real-life example
 near end   = real-world applications, common mistakes or myths
 last       = recap of the key points
{story_note}{last_note}
Rules:
- Return exactly {count} different sections, each about ONE clear idea.
- title: short, written in {language}.
- focus: one English sentence saying WHAT to explain and WHICH real-life example to use.
- image_query: ENGLISH search words (2 to 5) for ONE real photograph of a concrete visible subject
  that shows exactly this section (for example "solar panels rooftop house", "human heart anatomy",
  "wifi router home"). Never abstract words. Use "" for the last section.

Return JSON exactly like this:
{{"title": "Video title in {language}",
  "sections": [{{"title": "Section title", "focus": "what to explain and the real-life example",
                "image_query": "green leaf sunlight"}}]}}
"""
        result = ask_json(prompt, attempts=2, num_predict=3200)
        title = title or str(result.get("title") or "").strip()
        raw = result.get("sections") or result.get("scenes") or []
        added = 0
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            t = str(item.get("title") or "").strip()
            if not t or t.lower() in seen:
                continue
            seen.add(t.lower())
            sections.append({"title": t, "focus": str(item.get("focus") or "").strip()[:240],
                             "image_query": _clean_query(item.get("image_query"))})
            added += 1
            if len(sections) >= n:
                break
        empty_rounds = 0 if added else empty_rounds + 1
        if progress:
            progress(min(1.0, len(sections) / n) * 0.25, "Planning the lesson")
    if len(sections) < 4:
        raise ValueError("The AI could not plan the lesson. Please try again.")
    return title or "Educational Video", sections


def _expand_narration(scene, words, language, audience, difficulty):
    prompt = f"""
Rewrite and extend this teacher narration to about {words} words, written in {language}.
Topic: {scene['title']}
Keep the same topic. Explain it clearly step by step first, then give ONE specific real-life example that
students have seen (name the real object or place) and say what to notice in the picture, and end with
one sentence on why it matters. Audience: {audience}. Difficulty: {difficulty}.
Plain sentences for text-to-speech, no Markdown, no lists.

CURRENT NARRATION:
{scene['narration']}

Return JSON exactly like this: {{"narration": "the longer narration"}}
"""
    try:
        text = _tidy(ask_json(prompt, attempts=1, num_predict=1400).get("narration"))
        if len(text.split()) > len(scene["narration"].split()):
            scene["narration"] = text
    except Exception:
        logger.warning("Could not expand narration for %r", scene.get("title"))


def _script_ratio(text, language):
    """Share of the letters in `text` that are written in the script of `language` (1.0 = all of them)."""
    rng = SCRIPT_RANGES.get(str(language).strip().lower())
    letters = [c for c in str(text or "") if c.isalpha()]
    if not rng or not letters:
        return 1.0
    return sum(1 for c in letters if rng[0] <= ord(c) <= rng[1]) / len(letters)


def _scene_in_language(scene, language):
    """False if a Kannada/Hindi scene came back mostly in English (small AI models do this)."""
    if str(language).strip().lower() not in SCRIPT_RANGES:
        return True
    return _script_ratio(scene.get("narration", ""), language) >= 0.6


def _fix_language(scene, language):
    """Rewrite a scene that came back in the wrong language into `language`. True if it is right now."""
    payload = {"title": scene["title"], "narration": scene["narration"], "bullets": scene["bullets"],
               "visual_items": scene["visual_items"], "example_label": scene.get("example_label", ""),
               "key_terms": scene["key_terms"]}
    prompt = f"""
Translate and rewrite the teaching content below into {language}.
{LANGUAGE_NOTE.get(str(language).strip().lower(), '')}
Keep the same meaning, the same facts, the same order and the same number of items in every list.
Keep the narration about the same length. Plain sentences for text-to-speech, no Markdown.
In key_terms keep the keys "term" and "definition" and translate only their values.

CONTENT:
{json.dumps(payload, ensure_ascii=False)}

Return JSON with exactly the same keys: title, narration, bullets, visual_items, example_label, key_terms.
"""
    try:
        res = ask_json(prompt, attempts=2, num_predict=2200)
    except Exception:
        logger.warning("Could not rewrite scene %r in %s", scene.get("title"), language)
        return False
    narration = _tidy(res.get("narration"))
    if not narration or _script_ratio(narration, language) < 0.6:
        return False
    scene["narration"] = narration
    title = _tidy(res.get("title"))
    if title and _script_ratio(title, language) >= 0.5:
        scene["title"] = title
    items = [str(x).strip()[:40] for x in (res.get("visual_items") or []) if str(x).strip()][:5]
    if len(items) >= 2:
        scene["visual_items"] = items
    bullets = [str(x).strip() for x in (res.get("bullets") or []) if str(x).strip()][:4]
    if bullets:
        scene["bullets"] = bullets
    label = str(res.get("example_label") or "").strip()[:40]
    if label and scene.get("example_label"):
        scene["example_label"] = label
    terms = []
    for kt in (res.get("key_terms") or []):
        if isinstance(kt, dict) and str(kt.get("term", "")).strip():
            terms.append({"term": str(kt["term"]).strip(), "definition": str(kt.get("definition", "")).strip()})
    if terms:
        scene["key_terms"] = terms[:2]
    return True


def write_scene_batch(sections, first, n, source_text, style, difficulty, language, audience,
                      words, story, upload_index, outline_titles):
    """Write the full scenes for sections[first:first+SCENES_PER_CALL]."""
    batch = sections[first:first + SCENES_PER_CALL]
    lo = max(0, first - 6)
    hi = min(n, first + len(batch) + 6)
    context = "\n".join(f"{i + 1}. {outline_titles[i]}" for i in range(lo, hi))
    todo = "\n".join(
        f"{first + k + 1}. {s['title']}  (explain: {s['focus'] or 'the main idea'}; "
        f"photo idea: {s['image_query'] or 'none'})" for k, s in enumerate(batch))
    last_note = ("\nThe LAST scene of the whole video is in this batch: make it a short recap, "
                 "image_query \"\", example_query \"\" and visual_type list or flow."
                 if first + len(batch) >= n else "")
    upload_note = ""
    if upload_index is not None and first <= upload_index < first + len(batch):
        upload_note = (f"\nThe student UPLOADED a picture. In scene {upload_index + 1} set image_query to exactly "
                       "UPLOADED and explain what is visible in that picture.")
    story_note = ("\nThis is a story: image_query and example_query must be \"\" for every scene."
                  if story else "")
    ex_words = max(14, int(words * 0.45))
    in_words = max(14, words - ex_words)
    prompt = f"""
You are a teacher explaining a topic on a classroom screen full of real-world photographs.
Write ONLY scenes {first + 1} to {first + len(batch)} of a {n}-scene video.

VIDEO OUTLINE (context only, do not repeat other scenes):
{context}

SCENES TO WRITE NOW:
{todo}

SOURCE CONTENT (excerpt):
{_excerpt(source_text, first, n, 3000)}

{_style_block(style, difficulty, audience, language)}

Each scene has TWO parts, spoken one after the other. While part 1 is spoken the screen shows a real photo
of the idea; while part 2 is spoken the screen shows a real photo of the real-life example.

Rules:
1. explanation: about {in_words} words, 2 to 4 sentences, teacher voice. Explain the idea clearly, step by step,
   in simple words. Explain every technical term in plain words the first time it appears.
2. example: about {ex_words} words, 2 to 4 sentences. Give ONE specific real-life example that people actually
   see or use and NAME the real thing (for example "a phone charger", "a pressure cooker", "a traffic signal").
   Say how the example shows the idea, tell what to notice in its picture ("Look at...", "Notice..."), and end
   with one sentence on why it matters. The example must clearly match the explanation.
   Both parts: plain sentences for text-to-speech, no Markdown, no lists.
3. image_query: ENGLISH search words (2 to 5) for ONE real photograph of exactly what the explanation is about,
   a concrete visible subject. image_query_alt: a simpler fallback (1 to 3 words, the main object).
4. example_query: ENGLISH search words (2 to 5) for ONE real photograph of the real-life example you named
   (the same object as in the example text). example_label: the name of that example in {language}, max 4 words.
   Never use abstract words in any query.
5. visual_items: 3 to 5 SHORT labels (max 4 words) shown next to the picture one by one, in the same order as
   the narration talks about them.
6. Write title, explanation, example, example_label, bullets, key_terms and visual_items in {language}.
7. bullets: 2 to 3 short points (max 10 words). key_terms: 1 to 2 objects with a term and a one-sentence definition.
8. visual_description: one short sentence describing the picture.
9. visual_type (used only if no photo is found): flow = steps, hub = one idea with parts,
   compare = two sides, list = groups.{last_note}{upload_note}{story_note}

Return JSON exactly like this:
{{"scenes": [{{"title": "Scene title", "explanation": "text", "example": "text",
              "image_query": "green leaf sunlight", "image_query_alt": "green leaf",
              "example_query": "tomato plant garden", "example_label": "Tomato plant",
              "visual_description": "text", "bullets": ["point"],
              "visual_type": "flow", "visual_items": ["label one", "label two", "label three"],
              "key_terms": [{{"term": "Term", "definition": "Definition"}}]}}]}}
"""
    for _ in range(2):
        result = ask_json(prompt, attempts=1, num_predict=4200)
        raw = result.get("scenes")
        scenes = []
        for k, sc in enumerate(raw if isinstance(raw, list) else []):
            section = batch[min(k, len(batch) - 1)]
            clean = _clean_scene(sc, style, story, first + k, section)
            if clean:
                scenes.append(clean)
        if scenes:
            return scenes
    return []


def generate_educational_scenes(source_text, style, difficulty, language, audience,
                                has_user_image=False, minutes=DEFAULT_MINUTES, progress=None):
    """Plan and write the whole script for `minutes` minutes. progress(fraction 0..1, message)."""
    n, words = plan_length(minutes, language)
    story = style == "Storytelling"
    logger.info("Planning %.1f min video: %d scenes x ~%d words", minutes, n, words)

    title, sections = plan_outline(
        source_text, style, difficulty, language, audience, n, story,
        progress=(lambda f, m: progress(f, m)) if progress else None)
    n = len(sections)
    outline_titles = [s["title"] for s in sections]
    upload_index = 1 if has_user_image and n > 1 else (0 if has_user_image else None)

    scenes = []
    for first in range(0, n, SCENES_PER_CALL):
        last_idx = min(n, first + SCENES_PER_CALL)
        if progress:
            progress(0.25 + 0.75 * first / n, f"Writing scenes {first + 1} to {last_idx} of {n}")
        got = write_scene_batch(sections, first, n, source_text, style, difficulty, language, audience,
                                words, story, upload_index, outline_titles)
        for sc in got:
            # Kannada / Hindi must really be written in that script: if not, rewrite the scene
            if not _scene_in_language(sc, language):
                logger.warning("Scene %r was not written in %s. Rewriting it.", sc.get("title"), language)
                if not _fix_language(sc, language):
                    logger.warning("Scene %r is still not in %s after the rewrite.", sc.get("title"), language)
            # too short? ask ONCE for a longer, fuller explanation (the calm pause covers the rest)
            if len(sc["narration"].split()) < int(words * 0.7):
                _expand_narration(sc, words, language, audience, difficulty)
        scenes.extend(got)
    if not scenes:
        raise ValueError("The AI did not generate valid scenes. Please try again.")
    scenes = scenes[:MAX_SCENES]
    if not story and len(scenes) >= 3:                      # last scene = diagram recap
        scenes[-1]["image_query"] = ""
        scenes[-1]["image_query_alt"] = ""
        scenes[-1]["example_query"] = ""
        scenes[-1]["example_label"] = ""
        if scenes[-1]["visual_type"] not in ("list", "flow"):
            scenes[-1]["visual_type"] = "list"
    if progress:
        progress(1.0, "Script ready")
    return {"title": title, "scenes": scenes}


# ==================================================
# 4. TEXT EXTRACTION (PDF / TXT / images)
# ==================================================
def get_pytesseract():
    try:
        import pytesseract
    except ImportError as exc:
        raise ImportError("pytesseract is missing. Run: pip install pytesseract") from exc
    win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.isfile(win_path):
        pytesseract.pytesseract.tesseract_cmd = win_path
    return pytesseract


def extract_text(file_path):
    if not file_path:
        raise ValueError("No file was provided.")
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    ext = path.suffix.lower()

    if ext == ".pdf":
        try:
            import fitz
        except ImportError as exc:
            raise ImportError("PyMuPDF is missing. Run: pip install PyMuPDF") from exc
        with fitz.open(str(path)) as doc:
            text = "\n".join(page.get_text() for page in doc).strip()
            if not text:
                pyt = get_pytesseract()
                parts = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    parts.append(pyt.image_to_string(img))
                text = "\n".join(parts).strip()
        if not text:
            raise ValueError("Could not extract readable text from this PDF.")
        return text

    if ext == ".txt":
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            raise ValueError("The text file is empty.")
        return text

    if ext in IMAGE_EXTS:
        pyt = get_pytesseract()
        with Image.open(path) as img:
            text = pyt.image_to_string(img).strip()
        if not text:
            raise ValueError("No readable text found in this image.")
        return text

    raise ValueError("Unsupported file format. Supported: PDF, TXT, PNG, JPG, JPEG.")


def extract_pdf_best_image(file_path):
    """Return the largest embedded picture of a PDF as a temp JPG path (or None)."""
    try:
        import fitz
        best, best_area = None, 0
        with fitz.open(str(file_path)) as doc:
            for page in doc:
                for info in page.get_images(full=True):
                    pix = fitz.Pixmap(doc, info[0])
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    area = pix.width * pix.height
                    if area > best_area and pix.width >= 300 and pix.height >= 200:
                        best, best_area = pix.tobytes("png"), area
        if not best:
            return None
        out = TEMP_DIR / f"pdfimg_{uuid.uuid4().hex[:8]}.jpg"
        Image.open(io.BytesIO(best)).convert("RGB").save(out, "JPEG", quality=90)
        return str(out)
    except Exception:
        return None


# ==================================================
# 5. NARRATION  (natural neural voice, gTTS only as fallback)
# ==================================================
_tts_state = {"fallbacks": 0}
_tts_lock = threading.Lock()


def get_language_code(language):
    key = str(language).strip().lower()
    if key not in LANGUAGE_CODES:
        raise ValueError(f"Unsupported narration language: {language}")
    return LANGUAGE_CODES[key]


@lru_cache(maxsize=1)
def edge_tts_available():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        logger.warning("edge-tts is not installed (pip install edge-tts). Using the robotic gTTS voice.")
        return False


def voice_candidates(language, voice="Female"):
    """Neural voice names to try, best first."""
    gender = "male" if str(voice or "").strip().lower() == "male" else "female"
    return VOICES.get(str(language).strip().lower(), VOICES["english"])[gender]


def pick_voice(language, voice="Female"):
    return voice_candidates(language, voice)[0]


def _clean_for_speech(text):
    text = re.sub(r"https?://\S+", " ", str(text or ""))
    text = text.replace("&", " and ").replace("%", " percent ")
    text = re.sub(r"[*#_`>\[\]{}|~^]+", " ", text)
    text = re.sub(r"\(\s*\)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _edge_tts_save(text, voice_name, rate_pct, out_path):
    import edge_tts

    async def run():
        await edge_tts.Communicate(text, voice_name, rate=f"{int(rate_pct):+d}%").save(str(out_path))

    asyncio.run(run())


def generate_narration(text, output_path, language="English", voice="Female", rate_pct=None):
    """Record one scene. rate_pct: -30 (slower) ... +30 (faster); only the neural voice supports it."""
    text = _clean_for_speech(text)
    if not text:
        raise ValueError("Narration text cannot be empty.")
    if rate_pct is None:
        rate_pct = VOICE_BASE_RATE
    p = Path(output_path)
    last_error = None

    if edge_tts_available():
        for voice_name in voice_candidates(language, voice):
            for attempt in range(2):
                try:
                    _edge_tts_save(text, voice_name, rate_pct, p)
                    if p.exists() and p.stat().st_size > 0:
                        return str(p)
                except Exception as exc:                   # network hiccup / unknown voice: retry, then next voice
                    last_error = exc
                    time.sleep(0.8 + attempt)
        logger.warning("Neural voice failed (%s). Falling back to gTTS.", last_error)

    with _tts_lock:
        _tts_state["fallbacks"] += 1
    try:
        gTTS(text=text, lang=get_language_code(language), slow=False).save(str(p))
    except Exception as exc:
        logger.exception("Narration generation failed.")
        raise RuntimeError(f"Could not generate narration (the voice service needs internet): {exc}") from exc
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError("Narration audio file was not created.")
    return str(p)


# ==================================================
# 6. REAL-WORLD IMAGES  (Pexels / Pixabay / Wikipedia / Wikimedia Commons / Openverse / upload)
# ==================================================
_STOP = {"a", "an", "the", "of", "in", "on", "and", "with", "for", "to", "close", "up", "view", "photo", "image"}
_BAD_TITLE = ("logo", "icon", "flag of", "signature", "coat of arms", "stamp", "banner", "wordmark", "qr code",
              "map of", "locator", "disambiguation")
_used_urls = set()
_used_lock = threading.Lock()


def reset_used_images():
    with _used_lock:
        _used_urls.clear()


def _http_get(url, timeout=HTTP_TIMEOUT, headers=None):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def _strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()


def _words(query):
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP]


def _search_pexels(query, portrait):
    if not PEXELS_API_KEY:
        return []
    qs = urllib.parse.urlencode({"query": query, "per_page": 8,
                                 "orientation": "portrait" if portrait else "landscape"})
    data = json.loads(_http_get("https://api.pexels.com/v1/search?" + qs,
                                headers={"Authorization": PEXELS_API_KEY}))
    words = _words(query)
    ranked = []
    for i, p in enumerate(data.get("photos", [])):
        src = p.get("src", {})
        url = src.get("large") or src.get("medium")
        if not url:
            continue
        alt = str(p.get("alt") or "").lower()
        score = sum(1 for k in words if k in alt)
        ranked.append((-score, i, url, f"Photo: {p.get('photographer', 'Pexels')} / Pexels"))
    ranked.sort()
    return [(u, c, "Pexels") for _, _, u, c in ranked[:4]]


def _search_pixabay(query, portrait):
    if not PIXABAY_API_KEY:
        return []
    qs = urllib.parse.urlencode({"key": PIXABAY_API_KEY, "q": query, "image_type": "photo", "per_page": 10,
                                 "safesearch": "true", "min_width": 800,
                                 "orientation": "vertical" if portrait else "horizontal"})
    data = json.loads(_http_get("https://pixabay.com/api/?" + qs))
    words = _words(query)
    ranked = []
    for i, h in enumerate(data.get("hits", [])):
        url = h.get("largeImageURL") or h.get("webformatURL")
        if not url:
            continue
        tags = str(h.get("tags") or "").lower()
        score = sum(1 for k in words if k in tags)
        if score == 0 and len(words) >= 2:
            continue
        ranked.append((-score, i, url, f"Photo: {h.get('user', 'Pixabay')} / Pixabay"))
    ranked.sort()
    return [(u, c, "Pixabay") for _, _, u, c in ranked[:4]]


def _search_wikipedia(query, portrait):
    """The lead picture of the best matching Wikipedia article: usually exactly the right picture."""
    qs = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": query, "gsrlimit": 6,
        "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 1280, "format": "json"})
    data = json.loads(_http_get("https://en.wikipedia.org/w/api.php?" + qs))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    words = _words(query)
    out = []
    for p in pages:
        thumb = p.get("thumbnail") or {}
        title = p.get("title", "")
        low = title.lower()
        if not thumb.get("source") or thumb.get("width", 0) < 500:
            continue
        if any(b in low for b in _BAD_TITLE):
            continue
        if not any(w in low for w in words) and p.get("index", 99) > 1:
            continue
        out.append((thumb["source"], f"Wikipedia: {title}", "Wikipedia"))
    return out[:3]


def _search_commons(query, portrait):
    qs = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280, "format": "json"})
    data = json.loads(_http_get("https://commons.wikimedia.org/w/api.php?" + qs))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    words = _words(query)
    ranked = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        title = p.get("title", "").lower()
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if any(b in title for b in _BAD_TITLE):
            continue
        w, h = info.get("thumbwidth") or info.get("width", 0), info.get("thumbheight") or info.get("height", 0)
        if w < 500 or h < 300:
            continue
        score = sum(1 for k in words if k in title)
        idx = p.get("index", 99)
        if score == 0 and idx > 3:          # not relevant enough
            continue
        meta = info.get("extmetadata", {})
        artist = _strip_html(meta.get("Artist", {}).get("value", ""))[:40] or "Wikimedia contributor"
        lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        credit = f"{artist} / Wikimedia Commons" + (f" ({lic})" if lic else "")
        ranked.append((-score, idx, info.get("thumburl") or info.get("url"), credit))
    ranked.sort()
    return [(u, c, "Wikimedia Commons") for _, _, u, c in ranked[:4] if u]


def _search_openverse(query, portrait):
    qs = urllib.parse.urlencode({"q": query, "page_size": 8, "category": "photograph", "mature": "false"})
    data = json.loads(_http_get("https://api.openverse.org/v1/images/?" + qs))
    words = _words(query)
    ranked = []
    for r in data.get("results", []):
        title = str(r.get("title") or "").lower()
        tags = " ".join(str(t.get("name", "")) for t in (r.get("tags") or [])).lower()
        score = sum(1 for k in words if k in title or k in tags)
        if score == 0 or not r.get("url"):
            continue
        if (r.get("width") or 0) and (r.get("width") or 0) < 500:
            continue
        credit = f"{str(r.get('creator') or 'Unknown')[:40]} / Openverse"
        ranked.append((-score, r["url"], credit))
    ranked.sort()
    return [(u, c, "Openverse") for _, u, c in ranked[:3]]


def _download_image(url, out_path, min_w=500):
    raw = _http_get(url, timeout=DOWNLOAD_TIMEOUT)
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        if im.width < min_w:
            return False
        if max(im.size) > 1280:                       # the video is drawn small, no need for huge photos
            im.thumbnail((1280, 1280))
        im.save(out_path, "JPEG", quality=88)
    return True


def fetch_web_image(query, out_path, portrait=False):
    """Find a real photo for `query` that was not used in another scene. Returns (credit, source) or None."""
    if not query or not USE_WEB_IMAGES:
        return None
    for search in (_search_pexels, _search_pixabay, _search_wikipedia, _search_commons, _search_openverse):
        try:
            for url, credit, source in search(query, portrait):
                with _used_lock:
                    if url in _used_urls:
                        continue
                try:
                    if not _download_image(url, out_path):
                        continue
                    if not image_matches(out_path, query):
                        continue
                    with _used_lock:
                        _used_urls.add(url)
                    return credit, source
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("Image search (%s) failed for %r: %s", search.__name__, query, exc)
    return None


def _find_photo(queries, out_path, portrait):
    """Try the most specific search first, then simpler ones."""
    for query in dict.fromkeys(q.strip() for q in queries if q and q.strip()):
        hit = fetch_web_image(query, out_path, portrait)
        if hit:
            return hit
    return None


def attach_image(scene, idx, work_dir, portrait, user_image, topic):
    """
    Fills scene['images'] with up to two real photos, in the order they are shown:
      kind 'concept' (explains the idea) and kind 'example' (the real-life example, shown with a label).
    Also sets scene['image_path'] / image_credit / image_source from the first photo.
    """
    scene["images"] = []
    scene["image_path"], scene["image_credit"], scene["image_source"] = None, "", ""
    if scene["visual_type"] == "story":
        return
    work = Path(work_dir)
    images = []

    if scene.get("use_user_image") and user_image:
        out = work / f"photo_{idx}_u.jpg"
        try:
            with Image.open(user_image) as im:
                im.convert("RGB").save(out, "JPEG", quality=92)
            images.append(dict(path=str(out), credit="Your uploaded image", source="Upload",
                               kind="concept", label=""))
        except Exception:
            logger.warning("Could not use uploaded image.", exc_info=True)

    if not images:
        q = scene.get("image_query", "").strip()
        if q and not q.upper().startswith("UPLOADED"):
            alt = scene.get("image_query_alt", "").strip()
            words = q.split()
            queries = [q, alt, " ".join(words[:3]), " ".join(words[:2])]
            if idx == 1:
                queries.append(topic)          # only the first scene may fall back to the video topic
            out = work / f"photo_{idx}_a.jpg"
            hit = _find_photo(queries, out, portrait)
            if hit:
                images.append(dict(path=str(out), credit=hit[0], source=hit[1], kind="concept", label=""))

    eq = scene.get("example_query", "").strip()
    if eq and not eq.upper().startswith("UPLOADED"):
        words = eq.split()
        out = work / f"photo_{idx}_b.jpg"
        hit = _find_photo([eq, " ".join(words[:3]), " ".join(words[:2])], out, portrait)
        if hit:
            images.append(dict(path=str(out), credit=hit[0], source=hit[1], kind="example",
                               label=scene.get("example_label", "")))

    scene["images"] = images
    if images:
        scene.update(image_path=images[0]["path"], image_credit=images[0]["credit"],
                     image_source=images[0]["source"])


# ==================================================
# 7. FFMPEG + MUSIC
# ==================================================
def get_ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe",
              r"C:\ffmpeg\bin\ffmpeg.exe\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"):
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("FFmpeg was not found. Install it and add it to your Windows PATH.")


def run_ffmpeg(cmd, label):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg {label} failed: " + r.stderr[-1500:])


def get_duration(path, ffmpeg):
    r = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def _ff(path):
    return Path(path).resolve().as_posix().replace("'", "'\\''")


def combine_scene_videos(video_paths, output_path, work_dir, ffmpeg):
    list_file = Path(work_dir) / "video_list.txt"
    list_file.write_text("\n".join(f"file '{_ff(p)}'" for p in video_paths) + "\n", encoding="utf-8")
    run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c", "copy", "-movflags", "+faststart", str(output_path)], "video combination")
    return str(output_path)


# calm "classroom" loop: C - G - Am - F, soft pad + bass + gentle plucked arpeggio
_CHORDS = [
    (130.81, [261.63, 329.63, 392.00]),    # C
    (98.00, [246.94, 293.66, 392.00]),     # G
    (110.00, [220.00, 261.63, 329.63]),    # Am
    (87.31, [220.00, 261.63, 349.23]),     # F
]


def synthesize_music(path, chord_seconds=8, sr=22050):
    """Write a 32 second seamless music loop to `path` (WAV). Pure Python, runs only ONCE (then it is cached)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    n = chord_seconds * len(_CHORDS) * sr
    buf = [0.0] * n
    tau = 2 * math.pi
    pad_len = int((chord_seconds + 2) * sr)
    for ci, (bass, pad) in enumerate(_CHORDS):
        c0 = ci * chord_seconds * sr
        for i in range(pad_len):
            t = i / sr
            env = min(1.0, t / 1.5) * min(1.0, (chord_seconds + 2 - t) / 2.0)
            v = 1.2 * math.sin(tau * bass * t)
            for f in pad:
                v += math.sin(tau * f * t) + 0.25 * math.sin(tau * 2 * f * t)
            buf[(c0 + i) % n] += v * env * 0.12
        notes = pad + [pad[1] * 2]
        order = [0, 1, 2, 3, 2, 1, 0, 1]
        for k in range(chord_seconds * 2):
            f = notes[order[k % len(order)]] * 2
            start = c0 + int(k * 0.5 * sr)
            for i in range(int(1.4 * sr)):
                t = i / sr
                buf[(start + i) % n] += (math.sin(tau * f * t) * math.exp(-3.2 * t)
                                         * min(1.0, t / 0.01) * 0.10)
    peak = max(abs(x) for x in buf) or 1.0
    scale = 0.8 * 32767 / peak
    pcm = array("h", (int(x * scale) for x in buf))
    tmp = Path(str(path) + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def get_music_track(work_dir, ffmpeg):
    """Your own static/music/background.mp3 if present, otherwise the generated calm loop."""
    if MUSIC_FILE.is_file():
        return MUSIC_FILE
    GENERATED_MUSIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not GENERATED_MUSIC_FILE.is_file() or GENERATED_MUSIC_FILE.stat().st_size < 1000:
        logger.info("Creating the background music loop (one time)...")
        synthesize_music(GENERATED_MUSIC_FILE)
    return GENERATED_MUSIC_FILE


def add_background_music(video_path, output_path, work_dir, ffmpeg):
    """
    Mix the music under the voice with fade-in / fade-out.
    Several FFmpeg graphs are tried, from the best (music ducks a little while the teacher speaks)
    down to the simplest one that works on old FFmpeg builds.
    """
    track = get_music_track(work_dir, ffmpeg)
    total = get_duration(video_path, ffmpeg)
    fade_out = max(0.0, total - 3.0)
    vol = max(0.05, min(1.0, MUSIC_VOLUME))
    fmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
    music = f"[1:a]{fmt},volume={vol},afade=t=in:st=0:d=2,afade=t=out:st={fade_out:.2f}:d=3[m]"
    mixes = [
        # 1) best: music is a little quieter while the voice speaks, louder in pauses
        (f"[0:a]{fmt},asplit=2[vo][sc];{music};"
         "[m][sc]sidechaincompress=threshold=0.05:ratio=3:attack=50:release=800[duck];"
         "[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[a]"),
        # 2) plain mix, voice kept at full volume (newer FFmpeg)
        (f"[0:a]{fmt}[n];{music};"
         "[n][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[a]"),
        # 3) plain mix for older FFmpeg builds (no normalize option)
        (f"[0:a]{fmt}[n];{music};"
         "[n][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]"),
    ]
    last = None
    for graph in mixes:
        try:
            run_ffmpeg([
                ffmpeg, "-y", "-i", str(video_path), "-stream_loop", "-1", "-i", str(track),
                "-filter_complex", graph,
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total:.3f}", "-movflags", "+faststart", str(output_path)], "background music")
            return str(output_path)
        except RuntimeError as exc:
            last = exc
            logger.warning("Music mix variant failed, trying the next one: %s", str(exc)[-300:])
    raise last


# ==================================================
# 7b. PAINTER: photo "classroom screen", diagrams, story scenes
# ==================================================
POP = 0.7

PALETTES = [
    dict(name="ocean",  bg1=(6, 18, 58),  bg2=(16, 112, 196), a1=(255, 196, 0),   a2=(0, 229, 255)),
    dict(name="sunset", bg1=(58, 12, 92), bg2=(238, 98, 96),  a1=(255, 230, 100), a2=(125, 225, 255)),
    dict(name="forest", bg1=(5, 48, 52),  bg2=(28, 160, 112), a1=(255, 214, 10),  a2=(160, 255, 210)),
    dict(name="candy",  bg1=(72, 18, 120), bg2=(250, 108, 170), a1=(255, 236, 110), a2=(130, 230, 255)),
    dict(name="space",  bg1=(4, 4, 28),   bg2=(70, 34, 140),  a1=(255, 190, 60),  a2=(110, 200, 255), stars=True),
    dict(name="aurora", bg1=(10, 30, 80), bg2=(40, 180, 150), a1=(255, 150, 200), a2=(190, 255, 120)),
]
STYLE_PALETTES = {"Animated": [0, 4, 5, 2, 1, 3], "Storytelling": [1, 3, 2, 0, 5, 4],
                  "Educational": [0, 5, 2, 4, 1, 3], "Simple Explanation": [2, 0, 5, 1, 3, 4]}
ACCENTS = [(255, 99, 132), (54, 162, 235), (255, 170, 0), (34, 197, 148), (153, 102, 255), (255, 120, 60)]
WHITE = (255, 255, 255)
INK = (30, 30, 70)

_FV_FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts", "/usr/local/share/fonts",
                 str(Path.home() / ".fonts"), "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
_NAMES = {
    "latin": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "latin_bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "indic": ["Nirmala.ttf", "Nirmala.ttc", "NirmalaUI.ttf", "NotoSansKannada-Regular.ttf",
              "NotoSansDevanagari-Regular.ttf", "Lohit-Kannada.ttf", "Lohit-Devanagari.ttf"],
    "indic_bold": ["NirmalaB.ttf", "NirmalaB.ttc", "Nirmala.ttf", "Nirmala.ttc",
                   "NotoSansKannada-Bold.ttf", "NotoSansDevanagari-Bold.ttf"],
}


@lru_cache(maxsize=None)
def _find_font(kind):
    for name in _NAMES[kind]:
        for base in _FV_FONT_DIRS:
            b = Path(base)
            if not b.exists():
                continue
            direct = b / name
            if direct.is_file():
                return str(direct)
            if not base.startswith("C:"):
                try:
                    hit = next(b.rglob(name), None)
                except OSError:
                    hit = None
                if hit:
                    return str(hit)
    return None


@lru_cache(maxsize=512)
def _font(size, bold, indic):
    kinds = ([("indic_bold" if bold else "indic")] if indic else []) + [("latin_bold" if bold else "latin")]
    for kind in kinds:
        path = _find_font(kind)
        if path:
            try:
                return ImageFont.truetype(path, int(size))
            except OSError:
                continue
    try:
        return ImageFont.load_default(int(size))
    except TypeError:
        return ImageFont.load_default()


_SCR = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def _wrap(text, font, max_w):
    lines, cur = [], ""
    for w in str(text).split():
        trial = (cur + " " + w).strip()
        if _SCR.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


@lru_cache(maxsize=8192)
def _fit(text, w, h, max_size, min_size, bold, indic, gap):
    size = max(max_size, min_size)
    while True:
        f = _font(size, bold, indic)
        lines = _wrap(text, f, w)
        lh = int(size * gap)
        if (len(lines) * lh <= h and all(_SCR.textlength(l, font=f) <= w for l in lines)) or size <= min_size:
            break
        size -= 2
    return size, tuple(lines)


def _mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _ease_back(x):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _sparkle(d, cx, cy, s, fill):
    d.polygon([(cx, cy - 2 * s), (cx + .5 * s, cy - .5 * s), (cx + 2 * s, cy), (cx + .5 * s, cy + .5 * s),
               (cx, cy + 2 * s), (cx - .5 * s, cy + .5 * s), (cx - 2 * s, cy), (cx - .5 * s, cy - .5 * s)],
              fill=fill)


def split_steps(narration, n_items):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?।॥])\s+", narration.strip()) if s.strip()]
    if not sentences:
        return [narration.strip() or "."]
    target = max(1, min(n_items, len(sentences)))
    size = math.ceil(len(sentences) / target)
    return [" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size)]


def check_indic_rendering(language):
    """Kannada and Hindi need a font AND Pillow's 'raqm' text shaping, or the letters look broken."""
    if str(language).strip().lower() not in SCRIPT_RANGES:
        return True
    ok = True
    if not _find_font("indic"):
        ok = False
        logger.warning("No Kannada/Hindi font was found. On Windows install 'Nirmala UI'; on Linux install "
                       "fonts-noto (Noto Sans Kannada / Devanagari). The on-screen text will show empty boxes.")
    try:
        from PIL import features
        has_raqm = bool(features.check("raqm"))
    except Exception:
        has_raqm = False
    if not has_raqm:
        ok = False
        logger.warning("Pillow has no 'raqm' text shaping, so Kannada/Hindi letters on the screen may look "
                       "broken (the spoken voice is not affected). Check: python -c \"from PIL import features; "
                       "print(features.check('raqm'))\"")
    return ok


class Painter:
    def __init__(self, style, size, language, show_subs, show_hl):
        self.style = style
        self.W, self.H = size
        self.portrait = self.H > self.W
        self.lang_key = str(language).strip().lower()
        self.indic = self.lang_key in ("kannada", "hindi")
        self.show_subs = bool(show_subs)
        self.show_hl = bool(show_hl)
        self._bg_cache = {}
        self.pal = PALETTES[0]
        self.rect = (0, 0, 10, 10)
        self.cur = {}
        self.col = []
        self._hub_center = None
        self._story_tip = (0, 0)
        self._speaker = 0
        self.total_len = 10.0
        # photo state
        self.photos = []
        self.photo_idx = -1
        self.photo_big = None
        self.photo_size = (10, 10)
        self.photo_pos = (0, 0)
        self.photo_outer = (0, 0, 10, 10)
        self.photo_mask = None
        self.photo_credit = ""
        self.photo_label = ""
        self.photo_t0 = 0.0
        self.photo_len = 10.0
        self.panel = (0, 0, 10, 10)
        self.pan_dir = 1

    # ---------- text ----------
    def text_in_box(self, d, text, box, color, max_size, min_size=16, bold=False, align="center", gap=1.18):
        x0, y0, x1, y1 = box
        if self.indic:
            gap = max(gap, 1.4)                  # Kannada / Devanagari letters are taller: more line space
        w, h = max(1, int(x1 - x0)), max(1, int(y1 - y0))
        size, lines = _fit(str(text), w, h, int(max_size), int(min_size), bool(bold), self.indic, gap)
        f = _font(size, bold, self.indic)
        lh = int(size * gap)
        y = y0 + (h - len(lines) * lh) / 2
        for line in lines:
            lw = d.textlength(line, font=f)
            x = x0 + (w - lw) / 2 if align == "center" else x0
            d.text((x, y), line, font=f, fill=color)
            y += lh

    # ---------- theme / geometry ----------
    def palette(self, scene_no):
        order = STYLE_PALETTES.get(self.style, STYLE_PALETTES["Animated"])
        return PALETTES[order[scene_no % len(order)]]

    def prepare(self, scene, scene_no, total):
        W, H = self.W, self.H
        self.pal = self.palette(scene_no)
        self.bg = self.background(self.pal)
        self.col = [self.bg.getpixel((W // 2, y)) for y in range(H)]
        self.ps = self.make_particles(scene_no, self.pal)
        self.cur = scene
        m = int(W * .05)
        self.m = m
        self.top = int(H * .035)
        self.head_h = int(H * (0.13 if not self.portrait else 0.11))
        self.cap_h = int(H * (0.25 if not self.portrait else 0.20)) if self.show_subs else 0
        terms = scene.get("key_terms") or []
        self.term_h = int(H * .09) if (self.show_hl and terms) else 0
        vis_top = self.top + self.head_h + int(H * .03)
        vis_bottom = H - self.cap_h - self.term_h - int(H * .03)
        self.rect = (m, vis_top, W - m, max(vis_top + 100, vis_bottom))
        self.pan_dir = 1 if scene_no % 2 == 0 else -1
        self.photo_big = None
        self.photo_idx = -1
        self.photos = []
        self.photo_label = ""
        self.photo_credit = ""
        if scene.get("visual_type") == "photo" and scene.get("images"):
            self.photos = list(scene["images"])
            self._layout_photo()

    # ---------- photo ----------
    def _layout_photo(self):
        x0, y0, x1, y1 = [int(v) for v in self.rect]
        gap = 12
        if self.portrait:
            sy = y0 + int((y1 - y0) * 0.54)
            self.photo_outer = (x0, y0, x1, sy - gap // 2)
            self.panel = (x0, sy + gap // 2, x1, y1)
        else:
            sx = x0 + int((x1 - x0) * 0.60)
            self.photo_outer = (x0, y0, sx - gap // 2, y1)
            self.panel = (sx + gap // 2, y0, x1, y1)
        ox0, oy0, ox1, oy1 = self.photo_outer
        inset = 6
        fw, fh = ox1 - ox0 - 2 * inset, oy1 - oy0 - 2 * inset
        self.photo_size = (fw, fh)
        self.photo_pos = (ox0 + inset, oy0 + inset)
        mask = Image.new("L", (fw, fh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], 14, fill=255)
        self.photo_mask = mask

    def set_photo(self, i, t0, length):
        """Show photo number `i` of this scene from time t0 on (the slow zoom restarts)."""
        self.photo_t0, self.photo_len = float(t0), max(0.5, float(length))
        if i == self.photo_idx:
            return
        info = self.photos[i]
        fw, fh = self.photo_size
        try:
            with Image.open(info["path"]) as im:
                im = im.convert("RGB")
                bw, bh = int(fw * 1.2), int(fh * 1.2)
                # blurred, darkened "cover" background so any picture shape fills the screen
                cover = max(bw / im.width, bh / im.height)
                bg = im.resize((max(bw, int(im.width * cover)), max(bh, int(im.height * cover))), Image.BILINEAR)
                left, top = (bg.width - bw) // 2, (bg.height - bh) // 2
                bg = bg.crop((left, top, left + bw, top + bh)).filter(ImageFilter.GaussianBlur(8))
                bg = Image.blend(bg, Image.new("RGB", bg.size, (10, 12, 28)), 0.45)
                # the real picture, fully visible (contain) in the middle
                fit = min(fw / im.width, fh / im.height)
                fg = im.resize((max(1, int(im.width * fit)), max(1, int(im.height * fit))), Image.LANCZOS)
                bg.paste(fg, ((bw - fg.width) // 2, (bh - fg.height) // 2))
        except Exception:
            logger.warning("Could not load photo %s", info.get("path"), exc_info=True)
            return
        self.photo_idx = i
        self.photo_big = bg
        src = info.get("source") or ""
        self.photo_credit = ("Image: " + src) if src and src != "Upload" else ""
        if info.get("kind") == "example":
            lab = str(info.get("label") or "").strip()
            self.photo_label = (EXAMPLE_LABEL.get(self.lang_key, EXAMPLE_LABEL["english"])
                                + (": " + lab if lab else ""))
        else:
            self.photo_label = ""

    def _paste_photo(self, img, T):
        fw, fh = self.photo_size
        bw, bh = self.photo_big.size
        p = min(1.0, max(0.0, (T - self.photo_t0) / max(0.1, self.photo_len)))
        e = p * p * (3 - 2 * p)
        z = 1.0 + 0.2 * e                       # slow zoom-in (Ken Burns)
        ww, wh = bw / z, bh / z
        sx, sy = bw - ww, bh - wh
        px = sx * (0.5 + self.pan_dir * 0.35 * (0.5 - e))
        py = sy * 0.5
        # ONE resize call that also crops (much faster than crop() followed by resize())
        crop = self.photo_big.resize((fw, fh), Image.BILINEAR, box=(px, py, px + ww, py + wh))
        img.paste(crop, self.photo_pos, self.photo_mask)
        d = ImageDraw.Draw(img)
        if self.photo_credit:
            f = _font(max(11, int(self.H * .022)), False, False)
            fsize = getattr(f, "size", 14)
            tw = d.textlength(self.photo_credit, font=f)
            bx, by = self.photo_pos[0] + 10, self.photo_pos[1] + fh - int(fsize * 1.9) - 8
            d.rounded_rectangle([bx, by, bx + tw + 16, by + int(fsize * 1.7)], 8, fill=(16, 18, 36))
            d.text((bx + 8, by + int(fsize * .3)), self.photo_credit, font=f, fill=(215, 225, 245))
        if self.photo_label:
            size = max(14, int(self.H * .034))
            while size > 12 and d.textlength(self.photo_label, font=_font(size, True, self.indic)) > fw - 50:
                size -= 1
            f = _font(size, True, self.indic)
            tw = d.textlength(self.photo_label, font=f)
            bx, by = self.photo_pos[0] + 12, self.photo_pos[1] + 12
            d.rounded_rectangle([bx, by, bx + tw + 26, by + int(size * 1.9)], 12, fill=self.pal["a1"])
            d.text((bx + 13, by + int(size * .35)), self.photo_label, font=f, fill=INK)

    # ---------- background ----------
    def background(self, pal):
        key = pal["name"]
        if key in self._bg_cache:
            return self._bg_cache[key]
        W, H = self.W, self.H
        c1, c2 = pal["bg1"], pal["bg2"]
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):
            k = y / max(1, H - 1)
            d.line([(0, y), (W, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * k) for i in range(3)))
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for fx, fy, fr, col in [(.88, .10, .34, pal["a2"]), (.06, .88, .30, pal["a1"]), (.55, .55, .22, pal["bg2"])]:
            r, cx, cy = H * fr, W * fx, H * fy
            od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (110,))
        ov = ov.filter(ImageFilter.GaussianBlur(H * 0.07))
        img = Image.alpha_composite(img.convert("RGBA"), ov)
        dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dots)
        step = 38
        for gx in range(step // 2, W, step):
            for gy in range(step // 2, H, step):
                dd.ellipse([gx - 2, gy - 2, gx + 2, gy + 2], fill=(255, 255, 255, 24))
        img = Image.alpha_composite(img, dots).convert("RGB")
        self._bg_cache[key] = img
        return img

    def make_particles(self, seed, pal):
        rnd = random.Random(seed * 131 + 7)
        W, H = self.W, self.H
        base = max(7, int(H * 0.012))
        ps = []
        for _ in range(7):                                   # was 14: fewer shapes = faster frames
            kind = rnd.choice(["bubble", "bubble", "dot", "star", "star", "plus"])
            r = base * (rnd.uniform(.9, 3.2) if kind == "bubble" else rnd.uniform(.5, 1.6))
            ps.append(dict(kind=kind, x=rnd.random() * W, y=rnd.random() * H, r=r,
                           sp=H * rnd.uniform(.015, .06), amp=W * rnd.uniform(.005, .02),
                           fq=rnd.uniform(.4, 1.2), ph=rnd.uniform(0, 6.28), tw=rnd.uniform(1.2, 3)))
        if pal.get("stars"):
            for _ in range(8):                               # was 16
                ps.append(dict(kind="star", x=rnd.random() * W, y=rnd.random() * H, r=base * rnd.uniform(.3, .8),
                               sp=H * rnd.uniform(.004, .012), amp=0, fq=1, ph=rnd.uniform(0, 6.28),
                               tw=rnd.uniform(1.5, 4)))
        return ps

    def draw_bg_motion(self, img, T):
        W, H = self.W, self.H
        pal = self.pal
        col = self.col
        d = ImageDraw.Draw(img)

        def tint(y, a, c=WHITE):
            px = col[int(min(H - 1, max(0, y)))]
            return _mix(px, c, a)

        for p in self.ps:
            r = p["r"]
            span = H + 4 * r + 40
            y = (p["y"] - p["sp"] * T) % span - 2 * r
            x = p["x"] + math.sin(T * p["fq"] + p["ph"]) * p["amp"] * 6
            if p["kind"] == "bubble":
                d.ellipse([x - r, y - r, x + r, y + r], fill=tint(y, .09), outline=tint(y, .38), width=2)
                d.ellipse([x - r * .55, y - r * .6, x - r * .2, y - r * .25], fill=tint(y, .45))
            elif p["kind"] == "dot":
                d.ellipse([x - r, y - r, x + r, y + r], fill=tint(y, .25, pal["a2"]))
            else:
                s = r * (0.65 + 0.35 * math.sin(T * p["tw"] + p["ph"]))
                _sparkle(d, x, y, max(1.0, s), tint(y, .6, pal["a1"] if p["kind"] == "star" else pal["a2"]))
        # one gentle wave at the bottom (was two, with a 32 px step); wider step = fewer points
        amp, fq, spd, a, yb = 0.014, 1.8, 0.8, .14, .965
        pts = [(0, H)]
        for xx in range(0, W + 1, 48):
            pts.append((xx, H * yb + math.sin(xx / W * math.pi * 2 * fq + T * spd) * H * amp))
        pts.append((W, H))
        d.polygon(pts, fill=tint(H * yb, a, pal["a2"]))

    # ---------- layers ----------
    def _layer(self):
        return Image.new("RGBA", (self.W, self.H), (255, 255, 255, 0))

    def _head_layer(self, scene, scene_no, total, caption, last):
        W, H, pal, m = self.W, self.H, self.pal, self.m
        L = self._layer()
        d = ImageDraw.Draw(L)
        d.rectangle([0, 0, W, 8], fill=(0, 0, 0, 70))
        d.rectangle([0, 0, int(W * (scene_no + 1) / max(1, total)), 8], fill=pal["a1"])
        top, hh = self.top, self.head_h
        d.rounded_rectangle([m, top, m + 10, top + hh], 5, fill=pal["a1"])
        f = _font(max(16, int(H * .03)), True, self.indic)
        counter = f"{scene_no + 1} / {total}"
        cw = d.textlength(counter, font=f)
        d.text((W - m - cw, top + 4), counter, font=f, fill=_mix(WHITE, pal["a2"], .35))
        self.text_in_box(d, scene["title"], (m + 26, top, W - m - cw - 20, top + hh), WHITE,
                         int(H * .075), 20, True, "left")
        if last and self.term_h:
            t0 = (scene.get("key_terms") or [{}])[0]
            ty0 = self.rect[3] + int(H * .015)
            d.rounded_rectangle([m, ty0 + 4, W - m, ty0 + self.term_h + 4], 16, fill=(0, 0, 0, 70))
            d.rounded_rectangle([m, ty0, W - m, ty0 + self.term_h], 16, fill=pal["a1"])
            label = t0.get("term", "")
            if t0.get("definition"):
                label += ": " + t0["definition"]
            self.text_in_box(d, label, (m + 18, ty0 + 3, W - m - 18, ty0 + self.term_h - 3), INK,
                             int(self.term_h * .48), 14, True)
        if self.show_subs and caption:
            sh = self.cap_h - int(H * .03)
            y0 = H - sh - int(H * .025)
            d.rounded_rectangle([m, y0, W - m, y0 + sh], 18, fill=(12, 14, 34, 235), outline=pal["a2"], width=3)
            self.text_in_box(d, caption, (m + 22, y0 + 6, W - m - 22, y0 + sh - 6), WHITE,
                             int(H * (0.05 if not self.portrait else 0.034)), 15)
        return L

    def _diagram(self, scene, k, bubble=False):
        L = self._layer()
        d = ImageDraw.Draw(L)
        fn = getattr(self, "_draw_" + scene["visual_type"], self._draw_list)
        fn(d, self.rect, scene["visual_items"], k, bubble)
        return L

    @staticmethod
    def _sprite(full, prev):
        r, g, b, a = ImageChops.difference(full, prev).split()
        m = ImageChops.lighter(ImageChops.lighter(r, g), ImageChops.lighter(b, a)).point(
            lambda v: 255 if v > 6 else 0)
        bbox = m.getbbox()
        if not bbox:
            return None
        spr = full.crop(bbox)
        spr.putalpha(ImageChops.multiply(spr.getchannel("A"), m.crop(bbox)))
        return spr, bbox

    def build_step(self, scene, scene_no, total, k0, k1, caption, last):
        head = self._head_layer(scene, scene_no, total, caption, last)
        vt = scene["visual_type"]
        sprites = []
        if vt == "story":
            base_d = self._diagram(scene, k1, False)
            full = self._diagram(scene, k1, True)
            s = self._sprite(full, base_d)
            if s:
                sprites.append((s[0], s[1], self._story_tip))
        else:
            base_d = self._diagram(scene, k0)
            prev = base_d
            for i in range(k0 + 1, k1 + 1):
                full = self._diagram(scene, i)
                s = self._sprite(full, prev)
                if s:
                    sprites.append((s[0], s[1], self._hub_center if vt == "hub" else None))
                prev = full
        return Image.alpha_composite(head, base_d), sprites

    # ---------- one frame ----------
    def render(self, base, sprites, T, t_step, step_dur):
        img = self.bg.copy()
        self.draw_bg_motion(img, T)
        img.paste(base, (0, 0), base)
        if self.photo_big is not None:
            self._paste_photo(img, T)
        if self.cur.get("visual_type") == "story":
            self._story_dynamic(img, T)
        d = ImageDraw.Draw(img)
        stagger = min(.45, step_dur / (len(sprites) + 2)) if sprites else 0
        for idx, (spr, bbox, anchor) in enumerate(sprites):
            tt = t_step - idx * stagger
            if tt < 0:
                continue
            s = _ease_back(min(1.0, tt / POP))
            if s > 0.02:
                sw, sh = spr.size
                bx0, by0 = bbox[0], bbox[1]
                ax, ay = anchor if anchor else (bx0 + sw / 2, by0 + sh / 2)
                sp = spr.resize((max(1, int(sw * s)), max(1, int(sh * s))), Image.BILINEAR)
                fade = min(1.0, tt / 0.25)
                if fade < 1:
                    sp.putalpha(sp.getchannel("A").point(lambda v, f=fade: int(v * f)))
                img.paste(sp, (int(ax + (bx0 - ax) * s), int(ay + (by0 - ay) * s)), sp)
            if tt < 0.7:
                cx, cy = bbox[0] + (bbox[2] - bbox[0]) / 2, bbox[1] + (bbox[3] - bbox[1]) / 2
                prog = tt / 0.7
                R = (min(bbox[2] - bbox[0], bbox[3] - bbox[1]) * .45 + 30) * (0.5 + prog)
                size = max(1.0, 9 * (1 - prog))
                for q in range(8):
                    ang = q * math.pi / 4 + .3
                    _sparkle(d, cx + R * math.cos(ang) * 1.3, cy + R * math.sin(ang),
                             size, self.pal["a1"] if q % 2 else WHITE)
        return img

    # ---------- shapes ----------
    def _glyph(self, d, kind, cx, cy, r):
        if kind == 0:
            pts = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                rr = r * (0.62 if i % 2 == 0 else 0.26)
                pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
            d.polygon(pts, fill=WHITE)
        elif kind == 1:
            d.polygon([(cx + .1 * r, cy - .65 * r), (cx - .4 * r, cy + .1 * r), (cx - .02 * r, cy + .1 * r),
                       (cx - .15 * r, cy + .65 * r), (cx + .4 * r, cy - .1 * r), (cx + .02 * r, cy - .1 * r)],
                      fill=WHITE)
        elif kind == 2:
            d.line([(cx - .4 * r, cy + .02 * r), (cx - .1 * r, cy + .35 * r), (cx + .45 * r, cy - .35 * r)],
                   fill=WHITE, width=max(3, int(r * .22)))
        elif kind == 3:
            rr = .3 * r
            for sx in (-.28, .28):
                d.ellipse([cx + sx * r - rr, cy - .15 * r - rr, cx + sx * r + rr, cy - .15 * r + rr], fill=WHITE)
            d.polygon([(cx - .55 * r, cy - .02 * r), (cx + .55 * r, cy - .02 * r), (cx, cy + .55 * r)], fill=WHITE)
        else:
            d.ellipse([cx - .38 * r, cy - .5 * r, cx + .38 * r, cy + .26 * r], fill=WHITE)
            d.rectangle([cx - .18 * r, cy + .2 * r, cx + .18 * r, cy + .44 * r], fill=WHITE)

    def _badge(self, d, cx, cy, r, idx, number=None):
        acc = ACCENTS[idx % len(ACCENTS)]
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=acc, outline=WHITE, width=3)
        if number is None:
            self._glyph(d, idx % 5, cx, cy, r)
        else:
            f = _font(int(r * 1.15), True, False)
            s = str(number)
            d.text((cx - d.textlength(s, font=f) / 2, cy - r * .68), s, font=f, fill=WHITE)

    def _box(self, d, xy, text, idx, number=None):
        x0, y0, x1, y1 = [int(v) for v in xy]
        acc = ACCENTS[idx % len(ACCENTS)]
        d.rounded_rectangle([x0 + 5, y0 + 7, x1 + 5, y1 + 7], 18, fill=(0, 0, 0, 70))
        d.rounded_rectangle([x0, y0, x1, y1], 18, fill=WHITE, outline=acc, width=4)
        wide = (x1 - x0) > 3 * (y1 - y0)
        pad = 12
        self.text_in_box(d, text, (x0 + pad, y0 + pad // 2, x1 - pad, y1 - pad // 2), INK,
                         int((y1 - y0) * (.62 if wide else .34)), 13, True)
        self._badge(d, x0 + 5, y0 + 5, 17, idx, number)

    def _arrow(self, d, p1, p2, color):
        d.line([p1, p2], fill=color, width=6)
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        s = 18
        d.polygon([p2, (p2[0] - s * math.cos(ang - .5), p2[1] - s * math.sin(ang - .5)),
                   (p2[0] - s * math.cos(ang + .5), p2[1] - s * math.sin(ang + .5))], fill=color)

    # ---------- diagrams (each draws items[:k]) ----------
    def _draw_photo(self, d, rect, items, k, bubble=False):
        """Classroom-screen frame around the photo + numbered label cards that pop in."""
        ox0, oy0, ox1, oy1 = self.photo_outer
        d.rounded_rectangle([ox0 + 5, oy0 + 7, ox1 + 5, oy1 + 7], 22, fill=(0, 0, 0, 90))
        d.rounded_rectangle([ox0, oy0, ox1, oy1], 22, fill=WHITE, outline=self.pal["a1"], width=4)
        self._draw_list(d, self.panel, items, k)

    def _draw_flow(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        n = len(items)
        gap = max(30, int(self.H * 0.085))
        w, h = x1 - x0, y1 - y0
        col = self.pal["a2"]
        if not self.portrait:
            bw = (w - gap * (n - 1)) / n
            bh = min(h * 0.75, 190)
            ty = y0 + (h - bh) / 2
            for i in range(k):
                bx = x0 + i * (bw + gap)
                self._box(d, [bx, ty, bx + bw, ty + bh], items[i], i, i + 1)
                if i > 0:
                    self._arrow(d, (bx - gap + 6, ty + bh / 2), (bx - 6, ty + bh / 2), col)
        else:
            bh = min((h - gap * (n - 1)) / n, 130)
            ty0 = y0 + (h - (n * bh + (n - 1) * gap)) / 2
            for i in range(k):
                by = ty0 + i * (bh + gap)
                self._box(d, [x0 + 16, by, x1 - 16, by + bh], items[i], i, i + 1)
                if i > 0:
                    cx = (x0 + x1) / 2
                    self._arrow(d, (cx, by - gap + 5), (cx, by - 5), col)

    def _draw_list(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        n = len(items)
        rh = min((y1 - y0) / n - 12, 100)
        ty = y0 + ((y1 - y0) - (n * rh + (n - 1) * 12)) / 2
        for i in range(k):
            by = ty + i * (rh + 12)
            d.rounded_rectangle([x0 + 54, by + 7, x1 + 5, by + rh + 7], 18, fill=(0, 0, 0, 70))
            d.rounded_rectangle([x0 + 48, by, x1, by + rh], 18, fill=WHITE, outline=ACCENTS[i % 6], width=4)
            self.text_in_box(d, items[i], (x0 + 82, by + 5, x1 - 16, by + rh - 5), INK, int(rh * .42), 13, True,
                             "left")
            self._badge(d, x0 + 24, by + rh / 2, rh * .36, i, i + 1)

    def _draw_hub(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        n = max(1, len(items))
        rx, ry = w * 0.36, h * 0.34
        bw = w * .24 if not self.portrait else w * .42
        bh = min(h * .2, 100)
        cr = min(w, h) * .14
        self._hub_center = (cx, cy)
        for i in range(k):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            d.line([(cx, cy), (cx + rx * math.cos(ang), cy + ry * math.sin(ang))], fill=self.pal["a2"], width=6)
        d.ellipse([cx - cr + 4, cy - cr + 6, cx + cr + 4, cy + cr + 6], fill=(0, 0, 0, 70))
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=self.pal["a1"], outline=WHITE, width=5)
        self.text_in_box(d, self.cur.get("title", ""), (cx - cr * .72, cy - cr * .72, cx + cr * .72, cy + cr * .72),
                         INK, int(cr * .5), 12, True)
        for i in range(k):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            px, py = cx + rx * math.cos(ang), cy + ry * math.sin(ang)
            self._box(d, [px - bw / 2, py - bh / 2, px + bw / 2, py + bh / 2], items[i], i)

    def _draw_compare(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        gap = 46
        cw = (x1 - x0 - gap) / 2
        for side, colr in enumerate((self.pal["a1"], self.pal["a2"])):
            cx0 = x0 + side * (cw + gap)
            d.rounded_rectangle([cx0, y0, cx0 + cw, y0 + 14], 7, fill=colr)
        left = [i for i in range(len(items)) if i % 2 == 0]
        right = [i for i in range(len(items)) if i % 2 == 1]
        rows = max(len(left), len(right), 1)
        rh = min(((y1 - y0 - 32) / rows) - 12, 105)
        for side, col in enumerate((left, right)):
            cx0 = x0 + side * (cw + gap)
            for r, i in enumerate(col):
                if i < k:
                    by = y0 + 32 + r * (rh + 12)
                    self._box(d, [cx0, by, cx0 + cw, by + rh], items[i], i)
        if k >= 2:
            vx, vy = x0 + cw + gap / 2, (y0 + y1) / 2
            d.ellipse([vx - 24, vy - 24, vx + 24, vy + 24], fill=self.pal["a1"], outline=WHITE, width=3)
            f = _font(22, True, False)
            d.text((vx - d.textlength("VS", font=f) / 2, vy - 14), "VS", font=f, fill=INK)

    def _draw_story(self, d, rect, items, k, bubble=True):
        x0, y0, x1, y1 = [int(v) for v in rect]
        w, h = x1 - x0, y1 - y0
        pal = self.pal
        sky_top = _mix(pal["bg1"], pal["bg2"], .55)
        sky_low = _mix(pal["bg2"], pal["a1"], .35)
        loc = Image.new("RGB", (w, h))
        ld = ImageDraw.Draw(loc)
        for yy in range(h):
            ld.line([(0, yy), (w, yy)], fill=_mix(sky_top, sky_low, min(1.0, yy / (h * .8))))
        ld.ellipse([w * .8, h * .1, w * .92, h * .1 + w * .12], fill=(255, 235, 120))
        g = h * .78
        ld.ellipse([-w * .1, g - h * .14, w * .45, g + h * .25], fill=(46, 150, 110))
        ld.ellipse([w * .4, g - h * .09, w * 1.1, g + h * .25], fill=(40, 135, 100))
        ld.rectangle([0, g + h * .02, w, h], fill=(34, 120, 90))
        tx = w * .47
        ld.rectangle([tx - 7, g - h * .16, tx + 7, g + 4], fill=(120, 80, 50))
        ld.ellipse([tx - h * .11, g - h * .34, tx + h * .11, g - h * .1], fill=(60, 170, 90))
        rnd = random.Random(5)
        for _ in range(14):
            fx, fy = 20 + rnd.random() * (w - 40), g + h * .06 + rnd.random() * (h * .14)
            ld.ellipse([fx - 4, fy - 4, fx + 4, fy + 4], fill=ACCENTS[rnd.randrange(6)])
        for i in range(len(items)):
            cx = w / 2 + (i - (len(items) - 1) / 2) * 26
            ld.ellipse([cx - 7, h - 22, cx + 7, h - 8], fill=pal["a1"] if i < k else (235, 235, 245))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], 24, fill=255)
        d._image.paste(loc, (x0, y0), mask)
        self._speaker = (k - 1) % 2 if k >= 1 else 0
        bw, bh = w * .62, h * .3
        bx, by = x0 + (w - bw) / 2, y0 + h * .06
        spx = x0 + w * (.22, .72)[self._speaker]
        tail_x = min(max(spx, bx + bw * .15), bx + bw * .85)
        self._story_tip = (spx, y0 + h * .44)
        if bubble and k >= 1:
            d.rounded_rectangle([bx + 5, by + 7, bx + bw + 5, by + bh + 7], 22, fill=(0, 0, 0, 70))
            d.rounded_rectangle([bx, by, bx + bw, by + bh], 22, fill=WHITE, outline=pal["a1"], width=4)
            d.polygon([(tail_x - bw * .05, by + bh - 3), (tail_x + bw * .05, by + bh - 3),
                       (spx, y0 + h * .44)], fill=WHITE)
            self.text_in_box(d, items[k - 1], (bx + 18, by + 10, bx + bw - 18, by + bh - 10), INK,
                             int(bh * .34), 13, True)

    def _story_dynamic(self, img, T):
        x0, y0, x1, y1 = [int(v) for v in self.rect]
        w, h = x1 - x0, y1 - y0
        reg = img.crop((x0, y0, x1, y1))
        d = ImageDraw.Draw(reg)
        for i in range(3):
            cw = w * (.14 + .03 * i)
            cx = ((i * w * .37 + T * w * .02 * (1 + i * .4)) % (w + cw * 2)) - cw
            cy = h * (.10 + .09 * i)
            for dx, dy, sc in ((0, 0, 1), (.45, -.12, .8), (-.4, .05, .7), (.8, .06, .65)):
                rr = cw * .28 * sc
                d.ellipse([cx + dx * cw - rr, cy + dy * cw - rr * .8, cx + dx * cw + rr, cy + dy * cw + rr * .8],
                          fill=(255, 240, 248))
        gy = h * .78
        for ci, (cxr, body, face, hair) in enumerate(((.22, (59, 130, 246), (255, 214, 170), (60, 40, 30)),
                                                       (.72, (244, 114, 182), (240, 190, 140), (30, 30, 60)))):
            talking = ci == self._speaker
            cx, r = w * cxr, h * .07
            bob = abs(math.sin(T * (5.5 if talking else 2.2) + ci * 1.7)) * h * (.035 if talking else .012)
            by = gy - h * .02 - bob
            wave = math.sin(T * (7 if talking else 3) + ci) * r * (.7 if talking else .25)
            aw = max(3, int(r * .42))
            d.line([(cx - r * .9, by - r * 2.2), (cx - r * 1.8, by - r * 1.5 + wave)], fill=face, width=aw)
            d.line([(cx + r * .9, by - r * 2.2), (cx + r * 1.8, by - r * 1.5 - wave)], fill=face, width=aw)
            d.rounded_rectangle([cx - r * .9, by - r * 2.6, cx + r * .9, by], 16, fill=body)
            d.ellipse([cx - r, by - r * 4.0, cx + r, by - r * 2.0], fill=face)
            d.pieslice([cx - r * 1.05, by - r * 4.1, cx + r * 1.05, by - r * 2.2], 180, 360, fill=hair)
            blink = ((T + ci * .6) % 3.0) < .12
            for ex in (-.4, .4):
                if blink:
                    d.line([(cx + ex * r - r * .15, by - r * 3.2), (cx + ex * r + r * .15, by - r * 3.2)],
                           fill=(30, 30, 30), width=2)
                else:
                    d.ellipse([cx + ex * r - r * .14, by - r * 3.35, cx + ex * r + r * .14, by - r * 3.05],
                              fill=(30, 30, 30))
            if talking and int(T * 6) % 2 == 0:
                d.ellipse([cx - r * .2, by - r * 2.75, cx + r * .2, by - r * 2.4], fill=(150, 40, 60))
            else:
                d.arc([cx - r * .5, by - r * 3.0, cx + r * .5, by - r * 2.35], 20, 160, fill=(150, 40, 60),
                      width=max(2, int(r * .12)))
        img.paste(reg, (x0, y0))


# --------------------------------------------------------------------------
# One scene -> MP4 (frames are piped straight into FFmpeg)
# --------------------------------------------------------------------------
def create_animated_scene(scene, index, total, painter, audio_path, audio_len,
                          output_path, work_dir, ffmpeg, aspect, subtitles, extra_pause=0.0):
    W, H = ASPECTS[aspect]
    RW, RH = painter.W, painter.H
    items = scene["visual_items"]
    n_items = len(items)
    steps = split_steps(scene["narration"], n_items)
    weights = [max(1, len(s)) for s in steps]
    eff_len = audio_len + extra_pause                 # extra calm time added to reach the requested length
    durs = [eff_len * x / sum(weights) for x in weights]
    durs[-1] += PAUSE
    total_len = eff_len + PAUSE
    fade = min(0.5, total_len / 4)

    painter.prepare(scene, index - 1, total)
    painter.total_len = total_len

    # which photo is on screen during each step: concept photo first, real-life example photo later
    photos = painter.photos
    ci = next((i for i, p in enumerate(photos) if p.get("kind") != "example"), None)
    ei = next((i for i, p in enumerate(photos) if p.get("kind") == "example"), None)
    ef = float(scene.get("example_fraction", 0.6))
    plan, acc, total_chars = [], 0, float(sum(weights))
    for j, wt in enumerate(weights):
        use_example = ei is not None and ci is not None and j > 0 and (acc / total_chars) >= ef - 0.05
        if not photos:
            plan.append(None)
        elif use_example or ci is None:
            plan.append(ei if ei is not None else ci)
        else:
            plan.append(ci)
        acc += wt
    seg = {}
    for j, pi in enumerate(plan):
        if pi is not None:
            seg[pi] = seg.get(pi, 0.0) + durs[j]
    if plan and plan[0] is not None:
        painter.set_photo(plan[0], 0.0, seg[plan[0]])

    scale = f"scale={W}:{H}:flags=bicubic," if (RW, RH) != (W, H) else ""
    log_path = Path(work_dir) / f"ffmpeg_scene_{index}.log"
    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-framerate", str(ANIM_FPS),
           "-i", "-", "-i", str(audio_path),
           "-vf", (f"{scale}tpad=stop_mode=clone:stop_duration=2,fade=t=in:st=0:d={fade:.2f},"
                   f"fade=t=out:st={total_len - fade:.2f}:d={fade:.2f},format=yuv420p"),
           "-af", ("highpass=f=70,acompressor=threshold=0.14:ratio=2.5:attack=5:release=120,"
                   f"apad=pad_dur={PAUSE + extra_pause:.2f}"),
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
           "-t", f"{total_len:.3f}", "-movflags", "+faststart", str(output_path)]
    with open(log_path, "w", encoding="utf-8", errors="ignore") as logf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=logf, stdout=subprocess.DEVNULL)
        try:
            T, reveal_prev = 0.0, 0
            for j, step_text in enumerate(steps):
                last = j == len(steps) - 1
                if plan[j] is not None and plan[j] != painter.photo_idx:
                    painter.set_photo(plan[j], T, seg[plan[j]])
                reveal = n_items if last else max(1, math.ceil((j + 1) * n_items / len(steps)))
                reveal = max(reveal, reveal_prev)
                base, sprites = painter.build_step(scene, index - 1, total, reveal_prev, reveal,
                                                  step_text if subtitles else "", last)
                nframes = max(2, int(round(durs[j] * ANIM_FPS)))
                for f in range(nframes):
                    frame = painter.render(base, sprites, T, f / ANIM_FPS, durs[j])
                    proc.stdin.write(frame.tobytes())
                    T += 1.0 / ANIM_FPS
                reveal_prev = reveal
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
        tail = log_path.read_text(encoding="utf-8", errors="ignore")[-1500:]
        raise RuntimeError("FFmpeg animated scene failed: " + tail)
    return str(output_path)


def _render_scene_job(args):
    """Runs in a worker process: draws and encodes ONE scene."""
    (scene, index, total, style, aspect, language, subtitles, highlights,
     audio, audio_len, clip, work_dir, ffmpeg, extra_pause) = args
    painter = Painter(style, RENDER_SIZES[aspect], language, subtitles, highlights)
    create_animated_scene(scene, index, total, painter, audio, audio_len,
                          clip, work_dir, ffmpeg, aspect, subtitles, extra_pause)
    return str(clip)


# ==================================================
# 8. FULL PIPELINE
# ==================================================
def _report(progress, percent, message):
    """Send progress to the web page; never let a reporting problem stop the video."""
    if progress:
        try:
            progress(percent, message)
        except Exception:
            logger.debug("progress callback failed", exc_info=True)


def _record_all(scenes, audios, language, voice, rate_pct, progress=None, base=30, span=20, extra_jobs=None):
    """Record every scene (parallel) and optionally run extra jobs (photo search) beside it."""
    extra_jobs = extra_jobs or []
    with ThreadPoolExecutor(max_workers=TTS_WORKERS + 4) as ex:
        tts = [ex.submit(generate_narration, scenes[k]["narration"], audios[k], language, voice, rate_pct)
               for k in range(len(scenes))]
        extras = [ex.submit(fn, *args) for fn, args in extra_jobs]
        tts_set = set(tts)
        total, done = len(tts) + len(extras), 0
        for f in as_completed(tts + extras):
            done += 1
            _report(progress, base + span * done / total, "Recording the voice and finding pictures")
            try:
                f.result()
            except Exception:
                if f in tts_set:
                    raise
                logger.warning("Image step failed; scene will use a diagram.", exc_info=True)


def generate_video_package(source_text, style="Educational", difficulty="Beginner",
                           language="English", audience="School Students",
                           aspect_ratio="16:9", subtitles=True, highlights=True, music=False,
                           image_path=None, use_web_images=True,
                           duration="Medium", duration_minutes=None, voice="Female",
                           progress=None):
    """
    Returns dict: filename, path, title, duration_seconds, scene_count, script_text, credits, voice_engine.
    duration_minutes: how long the video should be (1 .. MAX_VIDEO_MINUTES). Empty -> `duration`
                      (Short / Medium / Long) -> 3 minutes.
    voice: "Female" or "Male".
    progress: optional callback progress(percent, message).
    image_path: optional uploaded picture that should appear in the video.
    """
    t_start = time.time()
    timings = {}
    _report(progress, 2, "Reading your material")
    source_text = source_text or ""
    if image_path:
        desc = describe_image(image_path)
        if not source_text.strip():
            source_text = desc
        elif desc and desc not in source_text:
            source_text = f"{source_text}\n\nUPLOADED PICTURE SHOWS: {desc}"
    if not source_text.strip():
        raise ValueError("Please provide educational content.")

    raw_style = style
    style = normalize_style(style)
    difficulty = pick(difficulty, DIFFICULTY_GUIDE, "Beginner")
    audience = pick(audience, AUDIENCE_GUIDE, "School Students")
    language = pick(language, ["English", "Kannada", "Hindi"], "English")
    voice = pick(voice, ["Female", "Male"], "Female")
    check_indic_rendering(language)
    aspect_ratio = aspect_ratio or "16:9"
    if aspect_ratio not in ASPECTS:
        raise ValueError("Unsupported aspect ratio.")
    minutes = resolve_minutes(duration, duration_minutes)
    logger.info("Video request: style %r -> %r, %.1f min, %s, %s voice", raw_style, style, minutes, language, voice)

    _report(progress, 6, "Checking the AI and video tools")
    check_ollama_connection()
    ffmpeg = get_ffmpeg_path()
    video_id = uuid.uuid4().hex[:12]
    work_dir = TEMP_DIR / video_id
    work_dir.mkdir(parents=True, exist_ok=True)
    reset_used_images()
    with _tts_lock:
        _tts_state["fallbacks"] = 0

    try:
        # ---- 0) script (the AI) ----
        t0 = time.time()
        _report(progress, 12, "Writing the lesson script")
        content = generate_educational_scenes(
            source_text, style, difficulty, language, audience,
            has_user_image=bool(image_path), minutes=minutes,
            progress=lambda frac, msg: _report(progress, 12 + 18 * frac, msg))
        scenes = content["scenes"]
        n = len(scenes)
        portrait = aspect_ratio == "9:16"
        timings["script"] = time.time() - t0

        # which scene shows the uploaded picture?
        if image_path:
            flagged = [i for i, s in enumerate(scenes) if s["image_query"].upper().startswith("UPLOADED")]
            for i in (flagged or [0]):
                scenes[i]["use_user_image"] = True

        # ---- 1) voice + real photos for ALL scenes at once (network-bound -> threads) ----
        t0 = time.time()
        audios = [work_dir / f"scene_{i}.mp3" for i in range(1, n + 1)]
        topic = content["title"]
        extra_jobs = []
        for k in range(n):
            if use_web_images or scenes[k].get("use_user_image"):
                extra_jobs.append((attach_image, (scenes[k], k + 1, work_dir, portrait, image_path, topic)))
            else:
                scenes[k].update(images=[], image_path=None, image_credit="", image_source="")
        _report(progress, 30, "Recording the voice and finding pictures")
        _record_all(scenes, audios, language, voice, VOICE_BASE_RATE, progress, 30, 16, extra_jobs)

        for s in scenes:
            s.setdefault("images", [])
            s.setdefault("image_path", None)
            s.setdefault("image_credit", "")
            if s["images"] and s["visual_type"] != "story":
                s["visual_type"] = "photo"
        lens = [get_duration(a, ffmpeg) for a in audios]
        if any(x <= 0 for x in lens):
            raise RuntimeError("Could not read narration duration.")

        # ---- 1b) fine-tune the speaking speed ONLY when the voice is far from the requested minutes ----
        target_audio = max(10.0, minutes * 60 - n * PAUSE)
        ratio = sum(lens) / target_audio
        if edge_tts_available() and abs(ratio - 1) > RERECORD_TOLERANCE:
            old = 1 + VOICE_BASE_RATE / 100.0
            new_rate = int(max(-30, min(30, round((old * ratio - 1) * 100))))
            if new_rate != VOICE_BASE_RATE:
                logger.info("Voice is %.0f%% of the target length; re-recording at %+d%% speed", ratio * 100, new_rate)
                _report(progress, 46, "Adjusting the voice speed to your video length")
                _record_all(scenes, audios, language, voice, new_rate, progress, 46, 4)
                new_lens = [get_duration(a, ffmpeg) for a in audios]
                if all(x > 0 for x in new_lens):
                    lens = new_lens

        # still too short? add a calm pause to every scene so the video matches the requested minutes
        extras = [0.0] * n
        shortfall = target_audio - sum(lens)
        if shortfall > max(4.0, 0.03 * target_audio):
            per_scene = min(MAX_EXTRA_PAUSE, shortfall / n)
            extras = [per_scene] * n
        logger.info("Narration %.0fs (+%.0fs pauses) for a %.0fs target. Photos found for %d of %d scenes",
                    sum(lens), sum(extras), target_audio, sum(1 for s in scenes if s["images"]), n)
        if edge_tts_available() is False or _tts_state["fallbacks"]:
            logger.warning("%d scene(s) used the basic robotic voice. Install/upgrade edge-tts and check the "
                           "internet connection for the natural voice.", _tts_state["fallbacks"])
        timings["voice+photos"] = time.time() - t0

        clips = [work_dir / f"clip_{i}.mp4" for i in range(1, n + 1)]

        # ---- 2) render every scene ----
        t0 = time.time()
        jobs = [(scenes[k], k + 1, n, style, aspect_ratio, language, bool(subtitles), bool(highlights),
                 audios[k], lens[k], clips[k], work_dir, ffmpeg, extras[k]) for k in range(n)]
        workers = max(1, min(MAX_WORKERS, n))
        _report(progress, 50, f"Drawing and rendering scenes (0/{n})")
        try:
            if workers > 1:
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    futures = [ex.submit(_render_scene_job, job) for job in jobs]
                    for done, f in enumerate(as_completed(futures), 1):
                        f.result()
                        _report(progress, 50 + 42 * done / n, f"Drawing and rendering scenes ({done}/{n})")
            else:
                for done, job in enumerate(jobs, 1):
                    _render_scene_job(job)
                    _report(progress, 50 + 42 * done / n, f"Drawing and rendering scenes ({done}/{n})")
        except Exception as exc:
            logger.warning("Parallel render failed (%s). Falling back to sequential.", exc)
            for job in jobs:
                if not Path(job[10]).exists() or Path(job[10]).stat().st_size == 0:
                    _render_scene_job(job)
        timings["render"] = time.time() - t0

        # ---- 3) join (and optional music) ----
        t0 = time.time()
        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", content["title"]).strip("_") or "educational_video"
        final_path = GENERATED_DIR / f"{safe_title[:50]}_{video_id}.mp4"

        _report(progress, 93, "Putting the video together")
        if music:
            joined = work_dir / "joined.mp4"
            combine_scene_videos(clips, joined, work_dir, ffmpeg)
            _report(progress, 96, "Adding background music")
            try:
                add_background_music(joined, final_path, work_dir, ffmpeg)
            except Exception:
                logger.error("Background music failed; using video without music.", exc_info=True)
                shutil.copyfile(joined, final_path)
        else:
            combine_scene_videos(clips, final_path, work_dir, ffmpeg)

        if not final_path.exists():
            raise RuntimeError("Final MP4 video was not created.")
        timings["join+music"] = time.time() - t0

        logger.info("TIMING for a %.1f min video (%d scenes): %s | total %.0fs", minutes, n,
                    " | ".join(f"{k} {v:.0f}s" for k, v in timings.items()), time.time() - t_start)

        credits = sorted({im["credit"] for s in scenes for im in s.get("images", []) if im.get("credit")})
        return {
            "filename": final_path.name,
            "path": str(final_path),
            "title": content["title"],
            "duration_seconds": int(round(get_duration(final_path, ffmpeg))),
            "scene_count": n,
            "script_text": "\n\n".join(f"{s['title']}\n{s['narration']}" for s in scenes),
            "credits": credits,
            "voice_engine": "basic" if (not edge_tts_available() or _tts_state["fallbacks"]) else "neural",
        }
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            logger.warning("Could not remove temporary files.", exc_info=True)


def generate_video_from_file(file_path, style="Educational", difficulty="Beginner", language="English", **options):
    """
    Convenience entry point for uploads.
      PDF / TXT  -> text is extracted (first big picture inside a PDF is reused in the video)
      image      -> the picture itself is used in the video; its text (OCR) and/or a vision-model
                    description (OLLAMA_VISION_MODEL) become the lesson content.
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    image_path, text = None, ""
    if ext in IMAGE_EXTS:
        image_path = str(path)
        try:
            text = extract_text(path)
        except Exception:
            text = ""
        if not text.strip():
            text = describe_image(image_path)
        if not text.strip():
            raise ValueError("Could not understand this image. Install Tesseract (OCR) or set "
                             "OLLAMA_VISION_MODEL=llava and run: ollama pull llava")
    else:
        text = extract_text(path)
        if ext == ".pdf":
            image_path = extract_pdf_best_image(path)
    return generate_video_package(text, style, difficulty, language, image_path=image_path, **options)


def generate_video(source_text, style="Educational", difficulty="Beginner", language="English", **options):
    """Backward-compatible wrapper: returns the MP4 path as a string."""
    return generate_video_package(source_text, style, difficulty, language, **options)["path"]


build_educational_video = generate_video


# ==================================================
# 9. AI QUIZ (based on the real video script)
# ==================================================
def _sample_script(text, size=9000):
    """For long videos, take pieces from the whole script so the quiz covers the entire lesson."""
    if len(text) <= size:
        return text
    parts = [p for p in text.split("\n\n") if p.strip()]
    if not parts:
        return text[:size]
    per = max(1, size // len(parts))
    return "\n\n".join(p[:per] for p in parts)[:size]


def generate_quiz(script_text, language="English", difficulty="Beginner", count=5):
    """Returns a list of {question, options[4], correct_index, explanation}."""
    if not script_text or not script_text.strip():
        raise ValueError("No video script is available for this video.")
    prompt = f"""
Create {count} multiple-choice questions that test what a student learned from this lesson.
Use ONLY facts stated in the lesson. Difficulty: {difficulty}. Write in {language}.
{LANGUAGE_NOTE.get(str(language).strip().lower(), '')}

LESSON:
{_sample_script(script_text)}

Rules: exactly 4 options per question, exactly one correct, plausible wrong answers,
and a one or two sentence explanation of the correct answer.
Return JSON exactly like this:
{{"questions": [{{"question": "text", "options": ["a", "b", "c", "d"],
                 "correct_index": 0, "explanation": "text"}}]}}
"""
    for _ in range(3):
        data = ask_json(prompt, attempts=1)
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
            quiz.append({"question": question, "options": opts,
                         "correct_index": opts.index(correct),
                         "explanation": str(q.get("explanation", "")).strip()})
        if len(quiz) >= 3:
            return quiz[:count]
    raise ValueError("The AI could not create a valid quiz. Please try again.")