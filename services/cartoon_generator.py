"""
services/cartoon_generator.py  -  AI Cartoon & Animation Studio engine for EduVision

Pipeline (text prompt -> animated cartoon movie), 100% FREE by default
  1. Ollama (local, llama3.2:3b)     writes the story, characters, scenes, dialogue
  2. Pillow (PIL)                    DRAWS the cartoon scenes + characters yourself (no image API)
  3. Pillow + FFmpeg                 animates the characters (bobbing, blinking, talking mouths)
  4. edge-tts (free neural voices)   narrator + one voice per character  (gTTS is the fallback)
  5. FFmpeg                          combines clips + voices + SFX + music + subtitles

Modes (set in .env)
  CARTOON_MODE=free   (default)  no paid service, no API key.
      FREE_IMAGE_SOURCE=pillow         (default) scenes drawn locally with Pillow  <- NEW
      FREE_IMAGE_SOURCE=pollinations   AI pictures from the free Pollinations.ai API + FFmpeg pan/zoom
  CARTOON_MODE=fal    real AI animation through fal.ai (paid, needs FAL_KEY)
"""
import asyncio
import base64
import io
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw

try:
    import edge_tts
except ImportError:  # gTTS is used instead
    edge_tts = None

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True, encoding="utf-8-sig")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ configuration
FAL_KEY = os.getenv("FAL_KEY", "").strip()
FAL_IMAGE_MODEL = os.getenv("FAL_IMAGE_MODEL", "fal-ai/flux/schnell").strip()
FAL_VIDEO_MODEL = os.getenv("FAL_VIDEO_MODEL", "fal-ai/kling-video/v2.1/standard/image-to-video").strip()
FAL_VIDEO_IMAGE_FIELD = os.getenv("FAL_VIDEO_IMAGE_FIELD", "image_url").strip()
PARALLEL = max(1, min(4, int(os.getenv("CARTOON_PARALLEL", "3"))))

# CARTOON_MODE=free (default) -> nothing paid.   CARTOON_MODE=fal -> paid fal.ai animation.
CARTOON_MODE = os.getenv("CARTOON_MODE", "free").strip().lower()
FREE_MODE = CARTOON_MODE != "fal"
# pillow = draw scenes locally (default)   pollinations = free online AI pictures
FREE_IMAGE_SOURCE = os.getenv("FREE_IMAGE_SOURCE", "pillow").strip().lower()
USE_PILLOW = FREE_MODE and FREE_IMAGE_SOURCE != "pollinations"
FREE_IMAGE_MODEL = os.getenv("FREE_IMAGE_MODEL", "flux").strip()
ANIM_FPS = max(8, min(24, int(os.getenv("CARTOON_FPS", "15"))))
IMG_PARALLEL = 1 if (FREE_MODE and not USE_PILLOW) else PARALLEL

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

MUSIC_FILE = BASE_DIR / "static" / "music" / "background.mp3"
USER_AGENT = "EduVision-CartoonStudio/1.0"

STYLES = ["2D", "3D", "Anime", "Storybook", "Kids Cartoon", "Fantasy"]
LANGUAGES = {"English": "english", "Kannada": "kannada", "Hindi": "hindi"}
GTTS_LANG = {"English": "en", "Kannada": "kn", "Hindi": "hi"}
DURATION_SCENES = {"Short": 3, "Medium": 5, "Long": 8}       # scenes per movie
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
FAL_IMAGE_SIZE = {"16:9": "landscape_16_9", "9:16": "portrait_16_9", "1:1": "square_hd"}
SFX_NAMES = ["", "whoosh", "magic", "boing", "roar", "birds", "water", "pop", "footsteps", "wind"]
EMOTIONS = {"happy", "sad", "angry", "surprised", "scared", "excited", "calm", "curious", "proud"}

STYLE_PROMPTS = {
    "2D": "2D cartoon illustration, flat colors, bold clean outlines, vibrant, children's animation style",
    "3D": "3D animated cartoon movie frame, Pixar-like quality, soft cinematic lighting, cute expressive characters",
    "Anime": "anime style, cel shaded, vibrant colors, detailed background, studio quality animation frame",
    "Storybook": "children's storybook illustration, soft watercolor, pastel colors, hand painted, gentle",
    "Kids Cartoon": "cute kids cartoon, simple rounded shapes, bright primary colors, friendly and cheerful",
    "Fantasy": "fantasy cartoon illustration, magical glowing atmosphere, rich colors, whimsical",
}

EDGE_VOICES = {
    "english": {"female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
    "kannada": {"female": "kn-IN-SapnaNeural", "male": "kn-IN-GaganNeural"},
    "hindi": {"female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
}
# voice type -> (base voice, pitch, rate)
VOICE_PROFILES = {
    "narrator": ("female", "+0Hz", "-4%"),
    "female": ("female", "+0Hz", "+0%"),
    "male": ("male", "+0Hz", "+0%"),
    "child": ("female", "+28Hz", "+6%"),
    "deep": ("male", "-12Hz", "-6%"),
}

SOCIAL_PRESETS = {
    "tiktok": (1080, 1920, "TikTok"),
    "reels": (1080, 1920, "Instagram Reels"),
    "shorts": (1080, 1920, "YouTube Shorts"),
    "instagram": (1080, 1350, "Instagram post (4:5)"),
    "youtube": (1920, 1080, "YouTube (16:9)"),
}


class StudioError(ValueError):
    """An error whose message is safe and useful to show to the user."""


# ------------------------------------------------------------------ readiness
def get_ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe",
              r"C:\ffmpeg\bin\ffmpeg.exe\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"):
        if os.path.isfile(p):
            return p
    raise StudioError("FFmpeg was not found. Install it and add it to your Windows PATH.")


def animation_ready():
    """True when the movie maker can run (free mode needs no key)."""
    return FREE_MODE or bool(FAL_KEY)


def check_ready():
    """Raise StudioError if anything needed for animation is missing. Call BEFORE charging credits."""
    if not FREE_MODE and not FAL_KEY:
        raise StudioError("FAL_KEY is missing. Create a key at https://fal.ai/dashboard/keys, "
                          "add FAL_KEY=your_key to .env and restart Flask, "
                          "or set CARTOON_MODE=free to use the free engine.")
    if edge_tts is None and gTTS is None:
        raise StudioError("No voice package found. Run: pip install edge-tts gTTS")
    get_ffmpeg_path()
    return True


# ------------------------------------------------------------------ Ollama (story writing)
def _ollama_chat(system, user, temperature=0.7, num_predict=3500):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": "json", "stream": False, "keep_alive": "30m",
        "options": {"temperature": temperature, "num_ctx": 8192, "num_predict": num_predict},
    }
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            content = json.loads(resp.read().decode("utf-8")).get("message", {}).get("content", "")
    except urllib.error.HTTPError as exc:
        raise StudioError(f"Ollama error {exc.code}. Is the model '{OLLAMA_MODEL}' downloaded? "
                          f"Run: ollama pull {OLLAMA_MODEL}") from exc
    except Exception as exc:
        raise StudioError("Cannot reach Ollama. Start the Ollama app and try again.") from exc
    if not content:
        raise StudioError("Ollama returned an empty answer. Please try again.")
    return content


def _extract_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise StudioError("The AI did not return a valid story. Please try again.")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise StudioError("The AI returned broken JSON. Please try again.") from exc
    if not isinstance(data, dict):
        raise StudioError("The AI did not return a valid story. Please try again.")
    return data


def _words(text, limit):
    parts = str(text or "").split()
    return " ".join(parts[:limit]).strip()


def _clean(text, limit=300):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def sanitize_scene(raw, names, index=0):
    """Return a safe scene dict. `names` are the valid character names."""
    if not isinstance(raw, dict):
        raw = {}
    dialogue = []
    for d in (raw.get("dialogue") or [])[:3]:
        if not isinstance(d, dict):
            continue
        line = _words(d.get("line"), 16)
        if not line:
            continue
        who = _clean(d.get("character"), 60)
        match = next((n for n in names if n.lower() == who.lower()), None)
        emotion = _clean(d.get("emotion"), 20).lower()
        dialogue.append({
            "character": match or (names[0] if names else "Character"),
            "line": line,
            "emotion": emotion if emotion in EMOTIONS else "happy",
        })
    sfx = _clean(raw.get("sfx"), 20).lower()
    return {
        "title": _clean(raw.get("title"), 80) or f"Scene {index + 1}",
        "setting": _clean(raw.get("setting"), 300) or "a colorful magical place",
        "action": _clean(raw.get("action"), 400) or "the characters talk and move happily",
        "narration": _words(raw.get("narration"), 30),
        "dialogue": dialogue,
        "sfx": sfx if sfx in SFX_NAMES else "",
    }


def sanitize_story(raw, n_scenes=None):
    """Validate a story from Ollama or from the user's edits. Raises StudioError if unusable."""
    if not isinstance(raw, dict):
        raise StudioError("The story is not valid.")
    chars = []
    for c in (raw.get("characters") or [])[:4]:
        if not isinstance(c, dict) or not _clean(c.get("name"), 60):
            continue
        voice = _clean(c.get("voice"), 12).lower()
        chars.append({
            "name": _clean(c.get("name"), 60),
            "description": _clean(c.get("description"), 300),
            "look": _clean(c.get("look"), 300) or _clean(c.get("description"), 300) or "a friendly cartoon character",
            "voice": voice if voice in ("female", "male", "child", "deep") else "female",
        })
    if not chars:
        raise StudioError("The story needs at least one character. Please generate it again.")
    names = [c["name"] for c in chars]
    scenes = [sanitize_scene(s, names, i) for i, s in enumerate(raw.get("scenes") or []) if isinstance(s, dict)]
    scenes = [s for s in scenes if s["narration"] or s["dialogue"]]
    if n_scenes:
        scenes = scenes[:n_scenes]
    if len(scenes) < 1:
        raise StudioError("The story has no scenes with narration or dialogue.")
    if len(scenes) > 8:
        raise StudioError("A movie can have at most 8 scenes.")
    return {
        "title": _clean(raw.get("title"), 100) or "My Cartoon Movie",
        "logline": _clean(raw.get("logline"), 300),
        "characters": chars,
        "scenes": scenes,
    }


STORY_SYSTEM = ("You are a children's cartoon screenwriter. Write original, family-friendly, positive stories. "
                "Never use copyrighted characters. Always return valid JSON only.")


def generate_story(prompt, style="3D", language="English", duration="Medium"):
    n = DURATION_SCENES.get(duration, 5)
    prompt = _clean(prompt, 800)
    if len(prompt) < 5:
        raise StudioError("Please describe your cartoon idea in a sentence.")
    if style not in STYLES:
        style = "3D"
    user = f"""
Write an ORIGINAL cartoon movie story for this idea:
IDEA: {prompt}
CARTOON STYLE: {style}
SPOKEN LANGUAGE: {language}

Rules:
- Exactly {n} scenes with a beginning, a problem and a happy resolution.
- 1 to 4 original characters.
- Fields look, setting and action are in ENGLISH and very visual (colors, clothes, place, what is happening).
  In "look" name the animal or type (cat, rabbit, bear, dog, robot, dragon, boy, girl) and the main color.
  In "setting" use simple place words (forest, sea, space, snow, desert, city, room, night, garden).
- Fields title, narration and dialogue line are in {language}.
- narration: one sentence, up to 25 words. dialogue: 1 to 3 lines per scene, each up to 12 words.
- emotion is one of: happy, sad, angry, surprised, scared, excited, calm, curious, proud.
- voice is one of: female, male, child, deep.
- sfx is one of: whoosh, magic, boing, roar, birds, water, pop, footsteps, wind, or an empty string.

Return JSON exactly like this:
{{"title": "Movie title", "logline": "one sentence summary",
  "characters": [{{"name": "Name", "description": "personality and role", "look": "visual description: species, colors, clothes", "voice": "child"}}],
  "scenes": [{{"title": "Scene title", "setting": "where it happens", "action": "what the characters do and their expressions",
              "narration": "one narrator sentence",
              "dialogue": [{{"character": "Name", "line": "what they say", "emotion": "happy"}}],
              "sfx": "birds"}}]}}
"""
    last = None
    for _ in range(2):
        try:
            return sanitize_story(_extract_json(_ollama_chat(STORY_SYSTEM, user)), n)
        except StudioError as exc:
            last = exc
            if "Ollama" in str(exc):
                raise
    raise last


def regenerate_scene(story, index, instruction="", style="3D", language="English"):
    story = sanitize_story(story)
    if not 0 <= index < len(story["scenes"]):
        raise StudioError("That scene does not exist.")
    names = [c["name"] for c in story["characters"]]
    chars = "; ".join(f"{c['name']} ({c['look']})" for c in story["characters"])
    titles = " | ".join(f"{i + 1}. {s['title']}" for i, s in enumerate(story["scenes"]))
    user = f"""
Rewrite scene {index + 1} of this cartoon movie. Keep the same characters and keep the story flowing.
MOVIE: {story['title']} - {story['logline']}
CHARACTERS: {chars}
ALL SCENES: {titles}
CARTOON STYLE: {style}. SPOKEN LANGUAGE: {language}.
EXTRA INSTRUCTION FROM THE USER: {_clean(instruction, 300) or 'none, make it better and different'}
Fields setting and action are in ENGLISH. Fields title, narration and dialogue line are in {language}.
narration: one sentence up to 25 words. dialogue: 1 to 3 lines, each up to 12 words.
Use only these character names: {', '.join(names)}.
Return JSON exactly like:
{{"title": "...", "setting": "...", "action": "...", "narration": "...",
  "dialogue": [{{"character": "{names[0]}", "line": "...", "emotion": "happy"}}], "sfx": "whoosh"}}
"""
    scene = sanitize_scene(_extract_json(_ollama_chat(STORY_SYSTEM, user)), names, index)
    if not scene["narration"] and not scene["dialogue"]:
        raise StudioError("The AI could not rewrite this scene. Please try again.")
    return scene


# ------------------------------------------------------------------ fal.ai (only used when CARTOON_MODE=fal)
def _fal_http(url, payload=None, method="GET", timeout=60):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")[:400]
        if exc.code in (401, 403):
            raise StudioError(f"fal.ai refused the request ({exc.code}). Check FAL_KEY and that your "
                              f"fal.ai account has a positive balance. Details: {body}") from exc
        if exc.code == 429:
            raise StudioError("fal.ai says too many requests at once. Lower CARTOON_PARALLEL in .env "
                              "or wait a minute.") from exc
        raise StudioError(f"fal.ai error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise StudioError(f"Could not reach fal.ai: {exc.reason}") from exc


def fal_run(model, arguments, timeout=1200, poll=3.0):
    """Submit to the fal queue, poll until COMPLETED, return the model output dict."""
    handle = _fal_http(f"https://queue.fal.run/{model}", arguments, "POST")
    status_url, response_url = handle.get("status_url"), handle.get("response_url")
    if not status_url or not response_url:
        raise StudioError(f"Unexpected reply from fal.ai: {str(handle)[:200]}")
    deadline = time.time() + timeout
    while True:
        status = _fal_http(status_url)
        state = str(status.get("status", "")).upper()
        if state == "COMPLETED":
            break
        if state in ("FAILED", "ERROR", "CANCELLED"):
            raise StudioError(f"fal.ai could not finish this request ({state}).")
        if time.time() > deadline:
            raise StudioError("fal.ai took too long. Please try again.")
        time.sleep(poll)
    return _fal_http(response_url, timeout=120)


def _download(url, dest, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    if not Path(dest).exists() or Path(dest).stat().st_size == 0:
        raise StudioError("A downloaded file was empty.")
    return str(dest)


def fal_image(prompt, size, dest):
    """Generate one image. Returns (local_path, remote_url)."""
    out = fal_run(FAL_IMAGE_MODEL, {
        "prompt": prompt, "image_size": size, "num_images": 1,
        "num_inference_steps": 4, "enable_safety_checker": True}, timeout=300, poll=2.0)
    images = out.get("images") or []
    if not images or not images[0].get("url"):
        raise StudioError("fal.ai did not return an image (the prompt may have been blocked).")
    url = images[0]["url"]
    _download(url, dest)
    return str(dest), url


def fal_animate(image_url, prompt, seconds, dest):
    """Turn one still image into a real animated clip with the image-to-video model."""
    out = fal_run(FAL_VIDEO_MODEL, {
        FAL_VIDEO_IMAGE_FIELD: image_url,
        "prompt": prompt[:1500],
        "duration": str(seconds),
        "negative_prompt": "blurry, distorted, extra limbs, deformed, text, watermark, realistic photo, still image",
        "cfg_scale": 0.5,
    }, timeout=1500, poll=4.0)
    video = out.get("video") or {}
    if not video.get("url"):
        raise StudioError("fal.ai did not return a video (the scene may have been blocked).")
    _download(video["url"], dest, timeout=300)
    return str(dest)


# ------------------------------------------------------------------ FREE mode: Pollinations (optional)
def free_image(prompt, width, height, dest):
    """Draw one picture with the free Pollinations.ai image API (no key). Returns (path, None)."""
    from urllib.parse import quote
    last = None
    for attempt in range(3):
        url = (f"https://image.pollinations.ai/prompt/{quote(prompt[:900])}"
               f"?width={width}&height={height}&model={FREE_IMAGE_MODEL}&nologo=true"
               f"&seed={random.randint(1, 999999)}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
            with Image.open(io.BytesIO(data)) as im:
                im.convert("RGB").save(dest, "JPEG", quality=90)
            return str(dest), None
        except Exception as exc:  # busy / rate limited / not an image
            last = exc
            time.sleep(6 * (attempt + 1))
    raise StudioError("The free picture service is busy or not reachable right now. "
                      f"Please try again in a minute. ({type(last).__name__})")


def draw_image(prompt, size_key, dest, aspect="16:9"):
    """One picture, from fal.ai or the free Pollinations service depending on CARTOON_MODE."""
    if FREE_MODE:
        w, h = (768, 768) if size_key == "square_hd" else SIZES.get(aspect, (1280, 720))
        return free_image(prompt, w, h, dest)
    return fal_image(prompt, size_key, dest)


# =====================================================================================
#  NEW: PILLOW CARTOON ENGINE  (draws backgrounds + characters + animation, all local)
# =====================================================================================
def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(W, H, top, bottom):
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_lerp(top, bottom, y / max(1, H - 1)))
    return img


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


# theme -> (sky top, sky bottom, ground, far-hill)
THEME_COLORS = {
    "day": ((88, 180, 250), (200, 235, 255), (110, 200, 110), (90, 175, 100)),
    "forest": ((120, 200, 240), (210, 240, 230), (70, 170, 90), (50, 140, 80)),
    "night": ((15, 20, 60), (60, 60, 120), (40, 90, 70), (30, 70, 60)),
    "sea": ((100, 190, 250), (200, 235, 255), (40, 140, 210), (240, 220, 160)),
    "space": ((8, 6, 30), (50, 20, 80), (110, 110, 130), (80, 80, 100)),
    "snow": ((170, 200, 235), (235, 245, 255), (250, 252, 255), (215, 230, 245)),
    "desert": ((120, 190, 245), (255, 235, 190), (240, 205, 130), (225, 185, 110)),
    "city": ((110, 190, 245), (230, 240, 250), (120, 125, 135), (150, 160, 175)),
    "room": ((255, 236, 200), (255, 226, 180), (190, 140, 100), (255, 214, 150)),
}
THEME_WORDS = [
    ("space", ["space", "planet", "galaxy", "rocket", "alien", "asteroid", "star ship"]),
    ("sea", ["ocean", "sea ", " sea", "beach", "underwater", "boat", "island", "river", "lake", "ship", "pond"]),
    ("snow", ["snow", "ice ", "winter", "arctic", "frozen", "north pole"]),
    ("desert", ["desert", "sand", "pyramid", "camel", "dune"]),
    ("night", ["night", "dark", "moonlight", "bedtime", "midnight", "stars"]),
    ("city", ["city", "street", "town", "school", "village", "market", "road", "bus"]),
    ("room", ["room", "house", "kitchen", "classroom", "home", "library", "inside", "bedroom"]),
    ("forest", ["forest", "jungle", "wood", "garden", "tree", "mountain", "meadow", "farm", "park"]),
]


def pick_theme(scene):
    text = f" {scene['setting']} {scene['title']} {scene['action']} ".lower()
    for name, words in THEME_WORDS:
        if any(w in text for w in words):
            return name
    return "day"


def _cloud(d, x, y, s):
    for dx, dy, r in [(0, 0, 28), (32, -12, 36), (68, 0, 30), (34, 12, 30)]:
        d.ellipse([x + (dx - r) * s, y + (dy - r) * s, x + (dx + r) * s, y + (dy + r) * s], fill=(255, 255, 255))


def _sun(d, x, y, r):
    for a in range(0, 360, 30):
        rad = math.radians(a)
        d.line([x + math.cos(rad) * r * 1.2, y + math.sin(rad) * r * 1.2,
                x + math.cos(rad) * r * 1.7, y + math.sin(rad) * r * 1.7], fill=(255, 205, 40), width=max(3, int(r / 8)))
    d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 225, 60), outline=(255, 175, 0), width=max(2, int(r / 12)))


def _moon(d, x, y, r):
    d.ellipse([x - r, y - r, x + r, y + r], fill=(250, 245, 210))
    d.ellipse([x - r * 0.4, y - r * 0.5, x + r * 0.2, y + r * 0.1], fill=(235, 230, 190))
    d.ellipse([x + r * 0.1, y + r * 0.1, x + r * 0.55, y + r * 0.5], fill=(235, 230, 190))


def _tree(d, x, base, h, u):
    d.rectangle([x - h * 0.07, base - h * 0.45, x + h * 0.07, base], fill=(135, 90, 50))
    for dx, dy, r in [(0, 0.62, 0.34), (-0.2, 0.5, 0.26), (0.2, 0.5, 0.26), (0, 0.8, 0.26)]:
        d.ellipse([x + (dx - r) * h, base - (dy + r) * h, x + (dx + r) * h, base - (dy - r) * h],
                  fill=(60, 160, 80), outline=(40, 120, 60), width=max(2, int(2 * u)))


def _pine(d, x, base, h, snow=False):
    d.rectangle([x - h * 0.05, base - h * 0.2, x + h * 0.05, base], fill=(110, 75, 45))
    for i in range(3):
        top = base - h * (0.3 + 0.28 * i) - h * 0.35
        bot = base - h * (0.2 + 0.25 * i)
        w = h * (0.32 - 0.06 * i)
        d.polygon([(x, top), (x - w, bot), (x + w, bot)], fill=(40, 120, 80))
        if snow:
            d.polygon([(x, top), (x - w * 0.45, top + (bot - top) * 0.45), (x + w * 0.45, top + (bot - top) * 0.45)],
                      fill=(250, 252, 255))


def _flower(d, x, y, color, u):
    d.line([x, y, x, y - 28 * u], fill=(50, 140, 60), width=max(2, int(3 * u)))
    for a in range(0, 360, 72):
        rad = math.radians(a)
        cx, cy = x + math.cos(rad) * 8 * u, y - 34 * u + math.sin(rad) * 8 * u
        d.ellipse([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 6 * u], fill=color)
    d.ellipse([x - 4 * u, y - 38 * u, x + 4 * u, y - 30 * u], fill=(255, 220, 0))


def _house(d, x, base, w, u):
    h = w * 0.7
    d.rectangle([x, base - h, x + w, base], fill=(250, 215, 160), outline=(120, 80, 50), width=max(2, int(3 * u)))
    d.polygon([(x - w * 0.08, base - h), (x + w / 2, base - h - w * 0.45), (x + w * 1.08, base - h)],
              fill=(210, 80, 70), outline=(120, 40, 40))
    d.rectangle([x + w * 0.4, base - h * 0.55, x + w * 0.62, base], fill=(130, 90, 60))
    d.rectangle([x + w * 0.1, base - h * 0.7, x + w * 0.3, base - h * 0.45], fill=(170, 220, 250), outline=(90, 70, 50))


def _building(d, x, base, w, h, color, rnd):
    d.rectangle([x, base - h, x + w, base], fill=color)
    step = max(18, int(w / 4))
    for wy in range(int(base - h + 14), int(base - 30), step + 8):
        for wx in range(int(x + 10), int(x + w - step * 0.6), step):
            lit = rnd.random() > 0.35
            d.rectangle([wx, wy, wx + step * 0.45, wy + step * 0.5],
                        fill=(255, 235, 140) if lit else _shade(color, 0.7))


def make_background(scene, size, seed=0):
    """Draw a cartoon background for a scene. Returns an RGB PIL image."""
    W, H = size
    u = min(W, H) / 720.0
    theme = pick_theme(scene)
    rnd = random.Random(f"{scene['title']}|{seed}")
    top, bot, ground, hill = THEME_COLORS[theme]
    img = _gradient(W, H, top, bot)
    d = ImageDraw.Draw(img)
    horizon = int(H * 0.62)

    # ---- sky objects
    if theme in ("night", "space"):
        for _ in range(int(60 * (W * H) / (1280 * 720))):
            x, y, r = rnd.randint(0, W), rnd.randint(0, int(horizon * 0.95)), rnd.choice([1, 1, 2, 3]) * u
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 230))
    if theme == "night":
        _moon(d, W * 0.8, H * 0.14, 48 * u)
    elif theme == "space":
        px, py = W * 0.78, H * 0.2
        d.ellipse([px - 70 * u, py - 70 * u, px + 70 * u, py + 70 * u], fill=(235, 130, 90))
        d.ellipse([px - 110 * u, py - 14 * u, px + 110 * u, py + 14 * u], outline=(255, 215, 160), width=int(5 * u))
        d.ellipse([W * 0.2 - 32 * u, H * 0.18 - 32 * u, W * 0.2 + 32 * u, H * 0.18 + 32 * u], fill=(110, 170, 240))
    elif theme != "room":
        _sun(d, W * 0.84, H * 0.15, 40 * u)
        for _ in range(3):
            _cloud(d, rnd.randint(int(W * 0.03), int(W * 0.7)), rnd.randint(int(H * 0.06), int(H * 0.26)),
                   rnd.uniform(0.9, 1.5) * u)

    # ---- far hills / ground
    if theme == "sea":
        d.rectangle([0, horizon, W, H], fill=ground)
        for y in range(horizon, H, max(14, int(26 * u))):
            for x in range(-40, W + 40, max(40, int(80 * u))):
                off = (y // 10 % 2) * 30 * u
                d.arc([x + off, y, x + off + 60 * u, y + 20 * u], 200, 340, fill=(200, 235, 255), width=max(2, int(3 * u)))
        d.ellipse([-W * 0.2, H * 0.84, W * 0.55, H * 1.4], fill=hill)          # sandy shore
    elif theme == "room":
        d.rectangle([0, 0, W, H], fill=bot)
        d.rectangle([0, int(H * 0.7), W, H], fill=ground)
        d.rectangle([0, int(H * 0.7) - 8 * u, W, int(H * 0.7)], fill=_shade(ground, 0.8))
        wx, wy = W * 0.62, H * 0.12
        d.rectangle([wx, wy, wx + 190 * u, wy + 210 * u], fill=(150, 215, 250), outline=(120, 80, 50), width=int(8 * u))
        d.line([wx + 95 * u, wy, wx + 95 * u, wy + 210 * u], fill=(120, 80, 50), width=int(6 * u))
        d.line([wx, wy + 105 * u, wx + 190 * u, wy + 105 * u], fill=(120, 80, 50), width=int(6 * u))
        d.rectangle([W * 0.1, H * 0.14, W * 0.1 + 150 * u, H * 0.14 + 110 * u], fill=(255, 245, 230),
                    outline=(120, 80, 50), width=int(6 * u))
        d.ellipse([W * 0.1 + 40 * u, H * 0.14 + 25 * u, W * 0.1 + 110 * u, H * 0.14 + 85 * u], fill=(240, 120, 110))
        d.ellipse([W * 0.25, H * 0.8, W * 0.75, H * 0.97], fill=(220, 100, 120))     # rug
    elif theme == "city":
        d.rectangle([0, horizon, W, H], fill=ground)
        x = -10
        while x < W:
            bw, bh = rnd.randint(int(90 * u), int(170 * u)), rnd.randint(int(150 * u), int(340 * u))
            _building(d, x, horizon + 6 * u, bw, bh, rnd.choice([(150, 120, 190), (230, 130, 120), (120, 170, 210),
                                                                  (240, 190, 100), (130, 190, 150)]), rnd)
            x += bw + rnd.randint(4, 14)
        d.rectangle([0, int(H * 0.8), W, H], fill=(90, 95, 105))
        for x in range(0, W, int(110 * u)):
            d.rectangle([x, H * 0.885, x + 60 * u, H * 0.9], fill=(250, 235, 140))
    elif theme == "space":
        d.ellipse([-W * 0.3, horizon + 40 * u, W * 1.3, H * 1.9], fill=ground)
        for _ in range(6):
            cx, cy, r = rnd.randint(0, W), rnd.randint(int(H * 0.75), int(H * 0.95)), rnd.randint(int(14 * u), int(40 * u))
            d.ellipse([cx - r, cy - r * 0.5, cx + r, cy + r * 0.5], fill=hill)
    else:
        d.ellipse([-W * 0.2, horizon - 90 * u, W * 0.7, H * 1.2], fill=hill)
        d.ellipse([W * 0.35, horizon - 60 * u, W * 1.3, H * 1.25], fill=_shade(hill, 0.92))
        d.rectangle([0, horizon + 30 * u, W, H], fill=ground)
        d.ellipse([-W * 0.1, horizon + 10 * u, W * 1.1, horizon + 110 * u], fill=ground)

    # ---- props
    base = horizon + 40 * u
    if theme in ("forest", "day"):
        n = 7 if theme == "forest" else 3
        for _ in range(n):
            _tree(d, rnd.randint(int(W * 0.03), int(W * 0.97)), base + rnd.randint(-10, 30) * u, rnd.randint(130, 240) * u, u)
        if theme == "day":
            _house(d, W * 0.06, base + 10 * u, 170 * u, u)
        for _ in range(10):
            _flower(d, rnd.randint(10, W - 10), rnd.randint(int(H * 0.8), int(H * 0.97)),
                    rnd.choice([(255, 99, 132), (255, 205, 86), (170, 120, 255), (255, 255, 255)]), u)
    elif theme == "night":
        for _ in range(6):
            x, h = rnd.randint(0, W), rnd.randint(130, 230) * u
            d.ellipse([x - h * 0.3, base - h, x + h * 0.3, base - h * 0.1], fill=(25, 60, 55))
            d.rectangle([x - h * 0.05, base - h * 0.2, x + h * 0.05, base], fill=(60, 45, 40))
    elif theme == "snow":
        for _ in range(7):
            _pine(d, rnd.randint(0, W), base + rnd.randint(-10, 30) * u, rnd.randint(150, 260) * u, snow=True)
        for _ in range(60):
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice([2, 3, 4]) * u
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
    elif theme == "desert":
        px = W * 0.12
        d.polygon([(px, base), (px + 120 * u, base - 130 * u), (px + 240 * u, base)], fill=(230, 190, 110), outline=(180, 140, 70))
        for _ in range(3):
            x, h = rnd.randint(int(W * 0.4), int(W * 0.95)), rnd.randint(90, 160) * u
            d.rounded_rectangle([x - 12 * u, base - h, x + 12 * u, base + 20 * u], 12 * u, fill=(70, 150, 80))
            d.rounded_rectangle([x - 40 * u, base - h * 0.7, x - 24 * u, base - h * 0.35], 8 * u, fill=(70, 150, 80))
            d.rounded_rectangle([x + 24 * u, base - h * 0.8, x + 40 * u, base - h * 0.45], 8 * u, fill=(70, 150, 80))
    elif theme == "sea":
        bx, by = W * 0.55, horizon + 25 * u
        d.polygon([(bx - 90 * u, by), (bx + 90 * u, by), (bx + 60 * u, by + 36 * u), (bx - 60 * u, by + 36 * u)], fill=(200, 80, 70))
        d.line([bx, by, bx, by - 130 * u], fill=(110, 80, 50), width=int(5 * u))
        d.polygon([(bx + 4 * u, by - 125 * u), (bx + 80 * u, by - 10 * u), (bx + 4 * u, by - 10 * u)], fill=(255, 255, 255), outline=(150, 150, 150))
    return img


# ----- characters ---------------------------------------------------------------------------------
COLOR_WORDS = {
    "red": (230, 70, 70), "blue": (70, 130, 230), "green": (70, 175, 100), "yellow": (250, 205, 60),
    "orange": (250, 150, 50), "purple": (150, 100, 220), "violet": (150, 100, 220), "pink": (245, 130, 180),
    "brown": (160, 110, 70), "white": (245, 245, 250), "black": (60, 60, 70), "gray": (150, 155, 165),
    "grey": (150, 155, 165), "golden": (240, 190, 70), "silver": (180, 190, 205), "teal": (60, 180, 180),
}
PALETTE = [(239, 108, 108), (100, 140, 240), (250, 190, 80), (140, 100, 220), (80, 180, 140), (240, 140, 190)]
SKIN = (255, 224, 189)
KIND_WORDS = [
    ("robot", ["robot", "machine", "android"]),
    ("rabbit", ["rabbit", "bunny", "hare"]),
    ("cat", ["cat", "kitten", "fox", "tiger", "wolf"]),
    ("round", ["bear", "dog", "puppy", "mouse", "lion", "monkey", "panda", "elephant", "pig", "owl", "koala"]),
    ("dragon", ["dragon", "dinosaur", "monster", "dino"]),
]


def _actor_spec(ch):
    text = f"{ch['name']} {ch['look']}".lower()
    found = [(m.start(), c) for w, c in COLOR_WORDS.items() for m in [re.search(rf"\b{w}\b", text)] if m]
    colors = [c for _pos, c in sorted(found)]          # first color mentioned = main body color
    h = sum(ord(c) for c in ch["name"])
    kind = "human"
    for k, words in KIND_WORDS:
        if any(re.search(rf"\b{w}", text) for w in words):
            kind = k
            break
    body = colors[0] if colors else PALETTE[h % len(PALETTE)]
    accent = colors[1] if len(colors) > 1 else PALETTE[(h + 2) % len(PALETTE)]
    if kind == "human":
        shirt, hair = body, rnd_hair(h)
        return {"name": ch["name"], "kind": kind, "body": shirt, "head": SKIN, "accent": hair, "phase": (h % 7) * 0.9}
    return {"name": ch["name"], "kind": kind, "body": body, "head": body if kind != "robot" else (190, 200, 215),
            "accent": accent, "phase": (h % 7) * 0.9}


def rnd_hair(h):
    return [(80, 50, 30), (30, 30, 40), (200, 140, 60), (150, 70, 40)][h % 4]


def draw_actor(d, cx, base, s, spec, t, speaking, emotion):
    """One cartoon character. (cx, base) = centre-x and ground-y of the feet; s = scale; t = seconds."""
    ph = spec["phase"]
    bob = math.sin(t * 3.2 + ph) * 5 * s
    base = base + bob * 0.4
    body, head_c, acc = spec["body"], spec["head"], spec["accent"]
    ow = max(2, int(3 * s))
    outline = (30, 30, 40)

    # shadow
    d.ellipse([cx - 62 * s, base - 8 * s, cx + 62 * s, base + 12 * s], fill=(0, 0, 0, 0) if False else (70, 110, 70))

    # legs + feet
    for sx in (-1, 1):
        d.rectangle([cx + sx * 24 * s - 11 * s, base - 52 * s, cx + sx * 24 * s + 11 * s, base - 8 * s], fill=_shade(body, 0.6), outline=outline, width=ow)
        d.ellipse([cx + sx * 24 * s - 22 * s, base - 20 * s, cx + sx * 24 * s + 22 * s, base + 6 * s], fill=(55, 55, 65), outline=outline, width=ow)

    # tail for animals
    if spec["kind"] in ("cat", "dragon", "round"):
        wag = math.sin(t * 6 + ph) * 12 * s
        d.line([cx + 40 * s, base - 80 * s, cx + 85 * s + wag, base - 105 * s], fill=body, width=int(16 * s))

    # body
    top = base - 178 * s
    d.ellipse([cx - 54 * s, top, cx + 54 * s, base - 40 * s], fill=body, outline=outline, width=ow)
    if spec["kind"] != "human":
        d.ellipse([cx - 32 * s, top + 40 * s, cx + 32 * s, base - 56 * s], fill=_lerp(body, (255, 255, 255), 0.55))

    # arms
    sh_y = top + 40 * s
    swing = math.sin(t * 4 + ph) * 12 * s
    d.line([cx - 50 * s, sh_y, cx - 82 * s, sh_y + 56 * s + swing], fill=body, width=int(20 * s))
    d.ellipse([cx - 94 * s, sh_y + 46 * s + swing, cx - 70 * s, sh_y + 70 * s + swing], fill=head_c, outline=outline, width=ow)
    wave = math.sin(t * 9) * 16 * s if speaking else math.sin(t * 3 + ph) * 8 * s
    hx, hy = cx + 88 * s, sh_y - (28 * s if speaking else 0) + wave
    d.line([cx + 50 * s, sh_y, hx, hy + 12 * s], fill=body, width=int(20 * s))
    d.ellipse([hx - 12 * s, hy, hx + 12 * s, hy + 24 * s], fill=head_c, outline=outline, width=ow)

    # head
    hy0 = top - 52 * s
    hr = 60 * s
    if spec["kind"] == "robot":
        d.rounded_rectangle([cx - hr, hy0 - hr * 0.85, cx + hr, hy0 + hr * 0.85], 14 * s, fill=head_c, outline=outline, width=ow)
        d.line([cx, hy0 - hr * 0.85, cx, hy0 - hr * 1.3], fill=outline, width=ow)
        d.ellipse([cx - 9 * s, hy0 - hr * 1.5, cx + 9 * s, hy0 - hr * 1.2], fill=(240, 80, 80), outline=outline, width=ow)
    else:
        # ears behind the head
        if spec["kind"] == "cat":
            for sx in (-1, 1):
                d.polygon([(cx + sx * 12 * s, hy0 - hr * 0.7), (cx + sx * 58 * s, hy0 - hr * 0.5), (cx + sx * 46 * s, hy0 - hr * 1.35)],
                          fill=head_c, outline=outline)
        elif spec["kind"] == "rabbit":
            for sx in (-1, 1):
                d.ellipse([cx + sx * 26 * s - 15 * s, hy0 - hr * 2.0, cx + sx * 26 * s + 15 * s, hy0 - hr * 0.5], fill=head_c, outline=outline, width=ow)
                d.ellipse([cx + sx * 26 * s - 7 * s, hy0 - hr * 1.8, cx + sx * 26 * s + 7 * s, hy0 - hr * 0.7], fill=(250, 180, 190))
        elif spec["kind"] == "round":
            for sx in (-1, 1):
                d.ellipse([cx + sx * 44 * s - 20 * s, hy0 - hr * 1.05, cx + sx * 44 * s + 20 * s, hy0 - hr * 0.5], fill=head_c, outline=outline, width=ow)
        elif spec["kind"] == "dragon":
            for sx in (-1, 1):
                d.polygon([(cx + sx * 20 * s, hy0 - hr * 0.8), (cx + sx * 36 * s, hy0 - hr * 0.8), (cx + sx * 30 * s, hy0 - hr * 1.5)], fill=acc, outline=outline)
        d.ellipse([cx - hr, hy0 - hr, cx + hr, hy0 + hr], fill=head_c, outline=outline, width=ow)
        if spec["kind"] == "human":
            d.pieslice([cx - hr - 3 * s, hy0 - hr - 6 * s, cx + hr + 3 * s, hy0 + hr * 0.3], 180, 360, fill=acc, outline=outline)

    # eyes (blink every ~3 s)
    ey = hy0 - 6 * s
    blink = ((t + ph) % 3.4) < 0.12
    for sx in (-1, 1):
        ex = cx + sx * 22 * s
        if blink:
            d.line([ex - 10 * s, ey, ex + 10 * s, ey], fill=outline, width=ow)
        else:
            rr = 13 * s if emotion in ("surprised", "scared") else 11 * s
            d.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=(255, 255, 255), outline=outline, width=max(2, int(2 * s)))
            d.ellipse([ex - 5 * s, ey - 5 * s, ex + 5 * s, ey + 5 * s], fill=(20, 20, 30))
            d.ellipse([ex - 1 * s, ey - 4 * s, ex + 3 * s, ey], fill=(255, 255, 255))
    # brows
    by = ey - 20 * s
    for sx in (-1, 1):
        ex = cx + sx * 22 * s
        if emotion == "angry":
            d.line([ex - sx * 12 * s, by - 6 * s, ex + sx * 10 * s, by + 6 * s], fill=outline, width=ow + 1)
        elif emotion in ("sad", "scared"):
            d.line([ex - sx * 10 * s, by + 5 * s, ex + sx * 12 * s, by - 5 * s], fill=outline, width=ow)
        elif emotion in ("surprised", "curious"):
            d.arc([ex - 11 * s, by - 8 * s, ex + 11 * s, by + 8 * s], 200, 340, fill=outline, width=ow)
    # cheeks + nose
    d.ellipse([cx - 46 * s, ey + 12 * s, cx - 28 * s, ey + 26 * s], fill=(255, 170, 170))
    d.ellipse([cx + 28 * s, ey + 12 * s, cx + 46 * s, ey + 26 * s], fill=(255, 170, 170))
    if spec["kind"] in ("cat", "round", "rabbit"):
        d.ellipse([cx - 6 * s, ey + 8 * s, cx + 6 * s, ey + 18 * s], fill=(70, 50, 55))
    # mouth
    my = ey + 30 * s
    if speaking and int(t * 8 + ph) % 2 == 0:
        d.ellipse([cx - 13 * s, my - 4 * s, cx + 13 * s, my + 20 * s], fill=(150, 40, 60), outline=outline, width=ow)
    elif emotion in ("sad", "scared"):
        d.arc([cx - 16 * s, my + 2 * s, cx + 16 * s, my + 24 * s], 200, 340, fill=outline, width=ow)
    elif emotion == "surprised":
        d.ellipse([cx - 8 * s, my, cx + 8 * s, my + 18 * s], fill=(150, 40, 60), outline=outline, width=ow)
    elif emotion == "angry":
        d.line([cx - 13 * s, my + 8 * s, cx + 13 * s, my + 8 * s], fill=outline, width=ow)
    else:
        d.arc([cx - 18 * s, my - 10 * s, cx + 18 * s, my + 16 * s], 20, 160, fill=outline, width=ow)


def _actors_for(story, scene):
    return [_actor_spec(c) for c in _chars_in_scene(story, scene)]


def _emotion_of(scene, name):
    for dlg in scene["dialogue"]:
        if dlg["character"] == name:
            return dlg["emotion"]
    return "happy"


def draw_actors(img, specs, scene, t, speaker=None):
    W, H = img.size
    u = min(W, H) / 720.0
    s = u * (1.25 if W > H else 1.0)
    d = ImageDraw.Draw(img)
    n = len(specs)
    base_y = H * (0.88 if W > H else 0.8)
    for k, spec in enumerate(specs):
        cx = W * (0.5 + (k - (n - 1) / 2) * (0.27 if W > H else 0.3))
        draw_actor(d, cx, base_y, s, spec, t, speaking=(speaker == k), emotion=_emotion_of(scene, spec["name"]))


def draw_pillow_still(story, scene, size, dest, index=0):
    """One finished cartoon picture (used as the scene preview)."""
    bg = make_background(scene, size, index)
    draw_actors(bg, _actors_for(story, scene), scene, t=0.0, speaker=0)
    bg.save(dest, "JPEG", quality=92)
    return str(dest)


def animate_pillow(story, scene, index, size, seconds, dest, ffmpeg):
    """Render an animated clip frame by frame with Pillow and pipe the raw frames into FFmpeg."""
    W, H = size
    specs = _actors_for(story, scene)
    bg = make_background(scene, size, index)
    fps = ANIM_FPS
    frames = max(fps, int(seconds * fps))
    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for f in range(frames):
            t = f / fps
            img = bg.copy()
            speaker = int(t / 1.6) % len(specs) if specs else None
            draw_actors(img, specs, scene, t, speaker)
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
    except (BrokenPipeError, OSError) as exc:
        proc.kill()
        raise StudioError("FFmpeg stopped while the animation was being drawn.") from exc
    if proc.wait() != 0 or not Path(dest).is_file() or Path(dest).stat().st_size == 0:
        raise StudioError("FFmpeg could not build the animated scene.")
    return str(dest)


def ken_burns(image, seconds, size, dest, ffmpeg, variant=0):
    """Free 'animation': slow zoom / pan over a still picture, made with FFmpeg."""
    W, H = size
    fr = max(24, int(seconds * 24))
    center_y = "ih/2-(ih/zoom/2)"
    moves = [
        (f"1+0.30*on/{fr}", "iw/2-(iw/zoom/2)", center_y),             # slow zoom in
        ("1.25", f"(iw-iw/zoom)*on/{fr}", center_y),                   # pan left to right
        (f"1.30-0.30*on/{fr}", "iw/2-(iw/zoom/2)", center_y),          # slow zoom out
        ("1.25", f"(iw-iw/zoom)*(1-on/{fr})", center_y),               # pan right to left
    ]
    z, x, y = moves[variant % len(moves)]
    vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={fr}:s={W}x{H}:fps=24,format=yuv420p")
    run_ffmpeg([ffmpeg, "-y", "-i", Path(image).name, "-vf", vf, "-t", str(seconds),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-an", Path(dest).name],
               "free animation", cwd=str(Path(image).parent))
    return str(dest)


def _crop_user_image(path, aspect, dest):
    """Crop the user's picture to the movie shape and save it as a JPEG file."""
    W, H = SIZES[aspect]
    with Image.open(path) as im:
        im = im.convert("RGB")
        target, (w, h) = W / H, im.size
        if w / h > target:
            nw = int(h * target)
            im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / target)
            im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im.resize((W, H)).save(dest, "JPEG", quality=90)
    return str(dest)


def _retry(fn, tries=2, wait=4):
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except StudioError as exc:
            last = exc
            if "refused the request" in str(exc):   # do not retry key/balance problems
                raise
            logger.warning("Attempt %d failed: %s", attempt + 1, exc)
            time.sleep(wait)
    raise last


# ------------------------------------------------------------------ prompts
def _chars_in_scene(story, scene):
    text = " ".join([scene["action"], scene["narration"]] + [d["character"] for d in scene["dialogue"]]).lower()
    present = [c for c in story["characters"] if c["name"].lower() in text]
    return (present or story["characters"])[:3]


def character_prompt(style, ch):
    return (f"{STYLE_PROMPTS[style]}. Character design, full body, front view, plain light background, "
            f"one single character: {ch['name']}, {ch['look']}. Original character, no text, no watermark")


def keyframe_prompt(style, story, scene):
    look = "; ".join(f"{c['name']}: {c['look']}" for c in _chars_in_scene(story, scene))
    return (f"{STYLE_PROMPTS[style]}. {scene['setting']}. {scene['action']}. "
            f"Characters: {look}. Wide cinematic shot, characters clearly visible, no text, no watermark")


def motion_prompt(style, scene):
    emotions = ", ".join(sorted({d["emotion"] for d in scene["dialogue"]})) or "happy"
    return (f"{style} cartoon animation. {scene['action']}. The characters move naturally, "
            f"gesture and talk with expressive faces ({emotions}), gentle camera movement, "
            f"smooth lively animation, consistent character design, {scene['setting']}")


# ------------------------------------------------------------------ audio
def _voice_for(language, voice_type):
    base, pitch, rate = VOICE_PROFILES.get(voice_type, VOICE_PROFILES["female"])
    return EDGE_VOICES[LANGUAGES.get(language, "english")][base], pitch, rate


async def _edge_save(text, voice, pitch, rate, path):
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))


def speak(text, language, voice_type, dest):
    """Free voice: edge-tts first, gTTS as fallback (both need internet, neither needs a key)."""
    last = None
    if edge_tts is not None:
        voice, pitch, rate = _voice_for(language, voice_type)
        for _ in range(3):
            try:
                asyncio.run(_edge_save(text, voice, pitch, rate, dest))
                if Path(dest).exists() and Path(dest).stat().st_size > 0:
                    return str(dest)
            except Exception as exc:  # network hiccup
                last = exc
                time.sleep(1.5)
    if gTTS is not None:
        try:
            tld = "co.in" if language == "English" else "com"
            gTTS(text=text, lang=GTTS_LANG.get(language, "en"), tld=tld, slow=(voice_type == "narrator")).save(str(dest))
            if Path(dest).exists() and Path(dest).stat().st_size > 0:
                return str(dest)
        except Exception as exc:
            last = exc
    raise StudioError(f"Voice generation failed (needs internet): {last}")


def run_ffmpeg(cmd, label, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", cwd=cwd)
    if r.returncode != 0:
        raise StudioError(f"FFmpeg {label} failed: " + r.stderr[-900:])


def get_duration(path, ffmpeg):
    r = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def _srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


GAP = 0.25
LEAD = 0.3


def build_voice_track(story, scene, index, language, work_dir, ffmpeg):
    """Narrator + character lines -> voice_<i>.wav and subs_<i>.srt. Returns (wav, srt, length_seconds)."""
    voice_by_name = {c["name"]: c["voice"] for c in story["characters"]}
    segments = []
    if scene["narration"]:
        segments.append(("narrator", None, scene["narration"]))
    for d in scene["dialogue"]:
        segments.append((voice_by_name.get(d["character"], "female"), d["character"], d["line"]))
    if not segments:
        raise StudioError(f"Scene {index + 1} has no narration or dialogue.")

    files, durations = [], []
    for k, (vtype, _who, text) in enumerate(segments):
        f = Path(work_dir) / f"seg_{index}_{k}.mp3"
        speak(text, language, vtype, f)
        files.append(f)
        durations.append(get_duration(f, ffmpeg) or 1.5)

    cmd = [ffmpeg, "-y"]
    for f in files:
        cmd += ["-i", f.name]
    n = len(files)
    parts = "".join(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,apad=pad_dur={GAP}[a{i}];" for i in range(n))
    chain = "".join(f"[a{i}]" for i in range(n))
    wav = Path(work_dir) / f"voice_{index}.wav"
    cmd += ["-filter_complex", f"{parts}{chain}concat=n={n}:v=0:a=1[out]", "-map", "[out]", wav.name]
    run_ffmpeg(cmd, "voice mixing", cwd=str(work_dir))

    srt = Path(work_dir) / f"subs_{index}.srt"
    t, lines = LEAD, []
    for k, ((_v, who, text), dur) in enumerate(zip(segments, durations), start=1):
        label = f"{who}: {text}" if who else text
        lines.append(f"{k}\n{_srt_time(t)} --> {_srt_time(t + dur)}\n{label}\n")
        t += dur + GAP
    srt.write_text("\n".join(lines), encoding="utf-8")
    return str(wav), str(srt), LEAD + sum(durations) + GAP * n


SFX_FILTERS = {
    "whoosh": "anoisesrc=d=1.2:c=pink:a=0.6,bandpass=f=900:width_type=h:w=800,afade=t=in:d=0.4,afade=t=out:st=0.6:d=0.6",
    "magic": "sine=f=880:d=1.5,tremolo=f=12:d=0.7,aecho=0.8:0.7:60:0.5,afade=t=out:st=0.8:d=0.7",
    "boing": "sine=f=300:d=0.7,vibrato=f=14:d=0.9,afade=t=out:st=0.3:d=0.4",
    "roar": "anoisesrc=d=1.6:c=brown:a=0.8,lowpass=f=400,tremolo=f=20:d=0.7,afade=t=out:st=1.0:d=0.6",
    "birds": "sine=f=2800:d=1.6,tremolo=f=9:d=1,afade=t=in:d=0.2,afade=t=out:st=1.0:d=0.6",
    "water": "anoisesrc=d=1.8:c=pink:a=0.35,lowpass=f=1200,afade=t=in:d=0.4,afade=t=out:st=1.2:d=0.6",
    "pop": "sine=f=600:d=0.3,afade=t=out:st=0.05:d=0.25",
    "footsteps": "anoisesrc=d=1.6:c=brown:a=0.9,lowpass=f=250,tremolo=f=3:d=1",
    "wind": "anoisesrc=d=2.0:c=pink:a=0.4,lowpass=f=600,tremolo=f=0.6:d=0.8,afade=t=in:d=0.5,afade=t=out:st=1.3:d=0.7",
}


def make_sfx(kind, work_dir, index, ffmpeg):
    if kind not in SFX_FILTERS:
        return None
    out = Path(work_dir) / f"sfx_{index}.wav"
    try:
        run_ffmpeg([ffmpeg, "-y", "-f", "lavfi", "-i", SFX_FILTERS[kind], "-ar", "44100", "-ac", "2", out.name],
                   "sound effect", cwd=str(work_dir))
        return str(out)
    except StudioError:
        logger.warning("Sound effect %s failed; continuing without it.", kind, exc_info=True)
        return None


def get_music_track(work_dir, ffmpeg, user_audio=None):
    if user_audio and Path(user_audio).is_file():
        return str(user_audio)
    if MUSIC_FILE.is_file():
        return str(MUSIC_FILE)
    pad = Path(work_dir) / "pad.wav"
    run_ffmpeg([ffmpeg, "-y",
                "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
                "-f", "lavfi", "-i", "sine=frequency=277.18:sample_rate=44100",
                "-f", "lavfi", "-i", "sine=frequency=329.63:sample_rate=44100",
                "-filter_complex", "[0][1][2]amix=inputs=3:duration=longest,volume=2,tremolo=f=0.25:d=0.4,lowpass=f=900[a]",
                "-map", "[a]", "-t", "30", pad.name], "music synthesis", cwd=str(work_dir))
    return str(pad)


# ------------------------------------------------------------------ video assembly
_FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts", "/usr/local/share/fonts", "/Library/Fonts"]
_FONT_FILES = ["Nirmala.ttf", "NirmalaB.ttf", "Nirmala.ttc", "NirmalaUI.ttf", "arial.ttf", "segoeui.ttf",
               "NotoSansKannada-Regular.ttf", "NotoSansDevanagari-Regular.ttf", "DejaVuSans.ttf"]


def _prepare_fonts(work_dir):
    """Copy a few fonts next to the job so libass can find them with a relative fontsdir."""
    fonts = Path(work_dir) / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in _FONT_FILES:
        for base in _FONT_DIRS:
            src = Path(base) / name
            if src.is_file():
                try:
                    shutil.copyfile(src, fonts / name)
                except OSError:
                    pass
                break
    return fonts


def _sub_font_name(language):
    return "Nirmala UI" if language in ("Kannada", "Hindi") else "Arial"


def render_scene(index, total, clip, clip_len, voice_wav, srt, sfx, scene_len, size, language,
                 burn_subs, work_dir, ffmpeg):
    W, H = size
    out = Path(work_dir) / f"scene_{index}.mp4"
    fade = 0.3
    fs = 14 if H > W else 16
    sub = (f"subtitles=filename='{Path(srt).name}':fontsdir='fonts':force_style="
           f"'FontName={_sub_font_name(language)},FontSize={fs},PrimaryColour=&H00FFFFFF,"
           f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=18'")

    def build(with_subs):
        v = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=24,format=yuv420p")
        v += (f",{sub}" if with_subs else "")
        v += f",fade=t=in:st=0:d={fade},fade=t=out:st={max(0.1, scene_len - fade):.2f}:d={fade}[v]"
        if sfx:
            a = ("[1:a]aresample=44100,aformat=channel_layouts=stereo,apad[va];"
                 "[2:a]aresample=44100,aformat=channel_layouts=stereo,volume=0.35[sa];"
                 "[va][sa]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]")
        else:
            a = "[1:a]aresample=44100,aformat=channel_layouts=stereo,apad[a]"
        cmd = [ffmpeg, "-y", "-stream_loop", "-1", "-i", Path(clip).name, "-i", Path(voice_wav).name]
        if sfx:
            cmd += ["-i", Path(sfx).name]
        cmd += ["-filter_complex", f"{v};{a}", "-map", "[v]", "-map", "[a]", "-t", f"{scene_len:.2f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", out.name]
        return cmd

    if burn_subs:
        try:
            run_ffmpeg(build(True), f"scene {index + 1} render", cwd=str(work_dir))
            return str(out)
        except StudioError as exc:
            logger.warning("Subtitle burn failed, rendering scene without it: %s", exc)
    run_ffmpeg(build(False), f"scene {index + 1} render", cwd=str(work_dir))
    return str(out)


def join_scenes(scene_files, final_path, music, music_track, work_dir, ffmpeg):
    lst = Path(work_dir) / "list.txt"
    lst.write_text("".join(f"file '{Path(f).name}'\n" for f in scene_files), encoding="utf-8")
    joined = Path(work_dir) / "joined.mp4"
    run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy",
                "-movflags", "+faststart", joined.name], "joining scenes", cwd=str(work_dir))
    if music and music_track:
        try:
            run_ffmpeg([ffmpeg, "-y", "-i", joined.name, "-stream_loop", "-1", "-i", str(music_track),
                        "-filter_complex",
                        "[0:a]volume=1.0[n];[1:a]volume=0.10[m];"
                        "[n][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", str(final_path)],
                       "background music", cwd=str(work_dir))
            return str(final_path)
        except StudioError:
            logger.warning("Background music failed; using the movie without music.", exc_info=True)
    shutil.copyfile(joined, final_path)
    return str(final_path)


def _user_image_data_uri(path, aspect):
    """Crop the user's picture to the movie's aspect ratio and return a data URI (fal mode only)."""
    W, H = SIZES[aspect]
    with Image.open(path) as im:
        im = im.convert("RGB")
        target = W / H
        w, h = im.size
        if w / h > target:
            nw = int(h * target)
            im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / target)
            im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ------------------------------------------------------------------ the whole movie
def generate_movie(story, style, language, aspect_ratio, work_dir, final_dir, job_id,
                   burn_subs=True, music=True, sfx=True, user_image=None, user_audio=None,
                   progress=None, asset=None):
    """Build the movie. progress(percent, message) and asset(kind, index, filename) are optional callbacks.

    Returns dict(path, filename, title, duration_seconds, script_text, scene_count).
    """
    def _p(pct, msg):
        if progress:
            try:
                progress(pct, msg)
            except Exception:
                pass

    def _a(kind, i, name):
        if asset:
            try:
                asset(kind, i, name)
            except Exception:
                pass

    check_ready()
    ffmpeg = get_ffmpeg_path()
    story = sanitize_story(story)
    if style not in STYLES:
        style = "3D"
    if aspect_ratio not in SIZES:
        aspect_ratio = "16:9"
    size = SIZES[aspect_ratio]
    work_dir, final_dir = Path(work_dir), Path(final_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    scenes, chars = story["scenes"], story["characters"]
    n = len(scenes)

    # ---- 1. character reference images (fal mode / pollinations only; skipped in Pillow mode)
    _p(5, "Drawing the characters")

    def draw_char(i):
        dest = work_dir / f"char_{i}.jpg"
        draw_image(character_prompt(style, chars[i]), "square_hd", dest, aspect_ratio)
        _a("character", i, dest.name)

    char_jobs = [] if FREE_MODE else list(range(len(chars)))
    with ThreadPoolExecutor(max_workers=IMG_PARALLEL) as ex:
        futs = [ex.submit(draw_char, i) for i in char_jobs]
        for k, f in enumerate(as_completed(futs), start=1):
            try:
                f.result()
            except StudioError as exc:
                if "refused the request" in str(exc):
                    raise
                logger.warning("Character image failed: %s", exc)
            _p(5 + int(10 * k / max(1, len(chars))), f"Drawing the characters ({k} of {len(chars)})")

    # ---- 2. one keyframe per scene
    _p(15, "Painting the scene backgrounds")
    keyframes = [None] * n

    def draw_scene(i):
        dest = work_dir / f"scene_{i}.jpg"
        if FREE_MODE and i == 0 and user_image:
            _crop_user_image(user_image, aspect_ratio, dest)       # use the student's own picture
            url = None
        elif USE_PILLOW:
            draw_pillow_still(story, scenes[i], size, dest, i)     # drawn locally, no service needed
            url = None
        else:
            _path, url = _retry(lambda: draw_image(keyframe_prompt(style, story, scenes[i]),
                                                   FAL_IMAGE_SIZE[aspect_ratio], dest, aspect_ratio),
                                tries=4 if FREE_MODE else 2, wait=6 if FREE_MODE else 4)
        keyframes[i] = url
        _a("scene", i, dest.name)

    with ThreadPoolExecutor(max_workers=IMG_PARALLEL) as ex:
        futs = [ex.submit(draw_scene, i) for i in range(n)]
        for k, f in enumerate(as_completed(futs), start=1):
            f.result()
            _p(15 + int(20 * k / n), f"Painting the scene backgrounds ({k} of {n})")

    # ---- 3. voices, subtitles, sound effects
    _p(35, "Recording character voices")
    voices = [None] * n
    sfx_files = [None] * n

    def record(i):
        voices[i] = build_voice_track(story, scenes[i], i, language, work_dir, ffmpeg)
        if sfx and scenes[i]["sfx"]:
            sfx_files[i] = make_sfx(scenes[i]["sfx"], work_dir, i, ffmpeg)

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futs = [ex.submit(record, i) for i in range(n)]
        for k, f in enumerate(as_completed(futs), start=1):
            f.result()
            _p(35 + int(7 * k / n), f"Recording character voices ({k} of {n})")

    # ---- 4. animation for every scene
    _p(42, "Animating the scenes" if FREE_MODE else "Animating the scenes (this is the slow part)")
    clips, clip_len = [None] * n, [5] * n
    user_uri = _user_image_data_uri(user_image, aspect_ratio) if (user_image and not FREE_MODE) else None

    def animate(i):
        voice_len = voices[i][2]
        if FREE_MODE:
            seconds = int(voice_len + 1.5) + 1
            dest = work_dir / f"clip_{i}.mp4"
            if USE_PILLOW and not (i == 0 and user_image):
                try:
                    animate_pillow(story, scenes[i], i, size, seconds, dest, ffmpeg)
                    clips[i], clip_len[i] = str(dest), seconds
                    return
                except StudioError as exc:
                    logger.warning("Pillow animation failed (%s); using camera move instead.", exc)
            ken_burns(work_dir / f"scene_{i}.jpg", seconds, size, dest, ffmpeg, variant=i)
            clips[i], clip_len[i] = str(dest), seconds
            return
        seconds = 5 if voice_len + 0.6 <= 5 else 10
        dest = work_dir / f"clip_{i}.mp4"
        prompt = motion_prompt(style, scenes[i])
        if i == 0 and user_uri:
            try:
                fal_animate(user_uri, prompt, seconds, dest)
                clips[i], clip_len[i] = str(dest), seconds
                return
            except StudioError as exc:
                if "refused the request" in str(exc):
                    raise
                logger.warning("Animating the uploaded image failed (%s); using a generated picture.", exc)
        _retry(lambda: fal_animate(keyframes[i], prompt, seconds, dest))
        clips[i], clip_len[i] = str(dest), seconds

    done = 0
    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futs = [ex.submit(animate, i) for i in range(n)]
        for f in as_completed(futs):
            f.result()
            done += 1
            _p(42 + int(40 * done / n), f"Animating the scenes ({done} of {n} finished)")

    # ---- 5. FFmpeg: combine clips + audio + subtitles
    _p(82, "Adding voices, effects and subtitles")
    if burn_subs:
        _prepare_fonts(work_dir)
    scene_files = []
    for i in range(n):
        wav, srt, voice_len = voices[i]
        scene_len = max(voice_len + 0.4, 3.0)
        scene_files.append(render_scene(i, n, clips[i], clip_len[i], wav, srt, sfx_files[i], scene_len,
                                        size, language, burn_subs, work_dir, ffmpeg))
        _p(82 + int(10 * (i + 1) / n), f"Editing scene {i + 1} of {n}")

    _p(93, "Combining everything into one movie")
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", story["title"]).strip("_")[:40] or "cartoon"
    final_path = final_dir / f"cartoon_{safe}_{job_id[:10]}.mp4"
    track = get_music_track(work_dir, ffmpeg, user_audio) if music else None
    join_scenes(scene_files, final_path, music, track, work_dir, ffmpeg)
    if not final_path.exists() or final_path.stat().st_size == 0:
        raise StudioError("The final movie file was not created.")

    script = [story["title"], story["logline"]]
    for i, s in enumerate(scenes, start=1):
        script.append(f"Scene {i}: {s['title']}")
        if s["narration"]:
            script.append(s["narration"])
        script += [f"{d['character']}: {d['line']}" for d in s["dialogue"]]
    return {
        "path": str(final_path),
        "filename": final_path.name,
        "title": story["title"],
        "duration_seconds": int(round(get_duration(final_path, ffmpeg))),
        "script_text": "\n".join(x for x in script if x),
        "scene_count": n,
    }


# ------------------------------------------------------------------ social media export
def export_for_platform(src, dst, preset):
    """Re-frame the movie for TikTok / Reels / Shorts / Instagram / YouTube (blurred fill, no cropping)."""
    if preset not in SOCIAL_PRESETS:
        raise StudioError("Unknown export format.")
    W, H, _label = SOCIAL_PRESETS[preset]
    ffmpeg = get_ffmpeg_path()
    graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:5[bg];"
             f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    run_ffmpeg([ffmpeg, "-y", "-i", str(src), "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(dst)], f"{preset} export")
    return str(dst)