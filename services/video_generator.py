"""
EduVision video generation service  (services/video_generator.py)  -- VISUAL TEACHER VERSION

Pipeline
  topic / text / PDF / image
     -> (optional) vision model describes an uploaded picture
     -> Ollama writes a teacher-style script: every scene has
          narration + image_query (what real photo to show) + labels + visual_type
     -> REAL photographs are fetched for every scene (Pexels if PEXELS_API_KEY is set,
        otherwise Wikimedia Commons - free, no key needed)
     -> gTTS narration for all scenes (parallel)
     -> each scene is drawn as a "classroom screen":
            photo with slow zoom/pan  +  labels that pop in one by one as the teacher speaks
            + captions + key-term bar + animated themed background
        If no suitable photo is found (or you are offline) the scene automatically falls back to an
        animated diagram (flow / hub / compare / list), and the last scene is always a diagram recap.
     -> FFmpeg: fade transitions, optional background music -> final MP4
     -> optional AI quiz

Optional environment variables (.env)
  OLLAMA_URL, OLLAMA_MODEL           (already used)
  OLLAMA_VISION_MODEL=llava          describe uploaded images (ollama pull llava)
  PEXELS_API_KEY=xxxx                better quality realistic photos (free key from pexels.com/api)
  EDUVISION_WEB_IMAGES=0             disable internet photos (diagram-only mode)

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
import base64
import random
import shutil
import logging
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from functools import lru_cache
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter
from gtts import gTTS

# ==================================================
# 1. CONFIGURATION
# ==================================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)
logger = logging.getLogger(__name__)

GENERATED_DIR = BASE_DIR / "static" / "generated"
TEMP_DIR = GENERATED_DIR / "temp"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

MUSIC_FILE = BASE_DIR / "static" / "music" / "background.mp3"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
USE_WEB_IMAGES = os.getenv("EDUVISION_WEB_IMAGES", "1") != "0"
USER_AGENT = "EduVision/1.0 (educational project; contact: local-install)"

MAX_SCENES = 14
MAX_SOURCE_CHARS = 18000
PAUSE = 0.8
ANIM_FPS = 15

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280)}
RENDER_SIZES = {"16:9": (960, 540), "9:16": (540, 960)}

MAX_WORKERS = max(1, min(4, (os.cpu_count() or 2) - 1))
TTS_WORKERS = 4

STYLE_GUIDE = {
    "Educational": ("Teach like a classroom teacher using a big screen. Introduce with a real-world example, "
                    "explain each part with its own picture, show how it works in real life, end with a recap."),
    "Animated": ("Teach VISUALLY so anyone understands by SEEING. Start with a curious hook question. "
                 "Explain each idea with a simple everyday analogy. Say one short sentence per label, in the "
                 "same order the labels appear on screen ('First you see...', 'Next...', 'Then...', "
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


# ==================================================
# 2. OLLAMA
# ==================================================
def check_ollama_connection():
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


def generate_ollama_response(prompt, temperature=0.4):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content":
                "You are an expert teacher and educational video director. Create accurate, simple and "
                "engaging content for students. Always return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "format": "json",
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": temperature, "num_ctx": 8192, "num_predict": 4500},
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


def ask_json(prompt, attempts=2):
    last = None
    for _ in range(attempts):
        try:
            result = parse_json(generate_ollama_response(prompt))
            if isinstance(result, dict):
                return result
        except Exception as exc:
            last = exc
            logger.warning("Ollama JSON attempt failed: %s", exc)
    raise ValueError(f"Ollama did not return valid JSON. Please try again. ({last})")


def describe_image(image_path):
    """Use a local vision model (e.g. llava) to describe an uploaded picture. Returns '' if unavailable."""
    if not OLLAMA_VISION_MODEL:
        return ""
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((1024, 1024))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        payload = {
            "model": OLLAMA_VISION_MODEL, "stream": False, "keep_alive": "10m",
            "messages": [{"role": "user", "images": [b64], "content":
                          "Describe this picture for a teacher: list the main objects, people, structures or "
                          "processes you can see and what concept it teaches. Be factual, 5 sentences max."}],
        }
        req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8")).get("message", {}).get("content", "").strip()
    except Exception:
        logger.warning("Vision description failed.", exc_info=True)
        return ""


# ==================================================
# 3. SCENES (teacher-style script with image plan)
# ==================================================
def suggest_scene_range(text):
    words = len(text.split())
    if words < 60:
        return 5, 6
    if words < 400:
        return 6, 8
    return 7, 9


def generate_educational_scenes(source_text, style, difficulty, language, audience, has_user_image=False):
    low, high = suggest_scene_range(source_text)
    upload_rule = ""
    if has_user_image:
        upload_rule = ("\n11. The user UPLOADED a picture. In the ONE scene that should show it (usually scene 2) "
                       "set image_query to exactly UPLOADED. Narrate what is visible in that picture.")
    story = style == "Storytelling"
    prompt = f"""
You are a teacher explaining a topic on a classroom screen full of real-world pictures.
Create a video script from the content below.

SOURCE CONTENT:
{source_text[:MAX_SOURCE_CHARS]}

VIDEO STYLE: {style}. {STYLE_GUIDE.get(style, '')}
DIFFICULTY: {difficulty}. {DIFFICULTY_GUIDE.get(difficulty, '')}
TARGET AUDIENCE: {audience}. {AUDIENCE_GUIDE.get(audience, '')}
LANGUAGE: {language}

Scene order to follow:
 scene 1  = interesting real-world example / hook (a picture students know from daily life)
 scene 2  = a picture that shows the main topic
 next     = one scene per important component or step, each with its own picture
 then     = a scene showing how it works in real life
 last     = short recap of the important points (this one is drawn as a diagram, no photo)

Rules:
1. Use between {low} and {high} scenes. Never pad or repeat.
2. Write title, narration, bullets, key_terms and visual_items in {language}.
3. narration: 25 to 55 words, teacher voice, plain sentences for text-to-speech, no Markdown.
   Describe what is VISIBLE ("Look at this leaf...", "Notice the arrow...") - do not read the labels aloud
   word for word. Use EXACTLY one sentence per item in visual_items, in the same order.
4. visual_items: 3 to 5 SHORT labels (max 4 words each) that appear next to the picture one by one.
5. image_query: {'"" (empty) because this is a story' if story else
   'ENGLISH search words for ONE real photograph that shows exactly what the scene explains, 2 to 5 words, '
   'a concrete visible subject (e.g. "green leaf sunlight", "desktop computer motherboard", '
   '"router switch network cables", "human heart anatomy"). Never abstract words. Empty "" for the last scene.'}
6. bullets: 2 to 3 short points (max 10 words) - keep text minimal.
7. key_terms: 1 to 2 objects with a short term and a one-sentence simple definition.
8. visual_description: one short sentence describing the picture.
9. visual_type (used when no photo is found): flow = steps, hub = one idea with parts, compare = two sides,
   list = groups, story = storytelling only. The last scene must use list or flow.
10. Explain every technical term with a practical everyday example.{upload_rule}

Return JSON exactly like this:
{{"title": "Video title",
  "scenes": [{{"title": "Scene title", "narration": "text", "image_query": "green leaf sunlight",
              "visual_description": "text", "bullets": ["point"],
              "visual_type": "flow", "visual_items": ["label one", "label two", "label three"],
              "key_terms": [{{"term": "Term", "definition": "Definition"}}]}}]}}
"""
    result = ask_json(prompt)
    scenes = []
    for sc in result.get("scenes", []) if isinstance(result.get("scenes"), list) else []:
        if not isinstance(sc, dict):
            continue
        title = str(sc.get("title", "")).strip()
        narration = str(sc.get("narration", "")).strip()
        if not title or not narration:
            continue
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
            vtype = opts[len(scenes) % len(opts)]
        raw_items = sc.get("visual_items") or bullets
        items = [str(x).strip()[:40] for x in raw_items if str(x).strip()][:5]
        if len(items) < 2:
            items = [s.strip()[:36] for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()][:4]
        if len(items) < 2:
            items = (items + [title, "Example"])[:2]
        query = re.sub(r"[\"'\n\r]", " ", str(sc.get("image_query", "") or "")).strip()[:60]
        scenes.append({
            "title": title, "narration": narration, "bullets": bullets,
            "visual_description": str(sc.get("visual_description", "")).strip(),
            "key_terms": terms[:2],
            "visual_type": vtype, "visual_items": items,
            "image_query": "" if story else query,
        })
    if not scenes:
        raise ValueError("The AI did not generate valid scenes. Please try again.")
    scenes = scenes[:MAX_SCENES]
    if not story and len(scenes) >= 3:                      # last scene = diagram recap
        scenes[-1]["image_query"] = ""
        if scenes[-1]["visual_type"] not in ("list", "flow"):
            scenes[-1]["visual_type"] = "list"
    return {"title": str(result.get("title") or "Educational Video").strip(), "scenes": scenes}


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
# 5. NARRATION
# ==================================================
def get_language_code(language):
    key = str(language).strip().lower()
    if key not in LANGUAGE_CODES:
        raise ValueError(f"Unsupported narration language: {language}")
    return LANGUAGE_CODES[key]


def generate_narration(text, output_path, language="English"):
    if not text or not text.strip():
        raise ValueError("Narration text cannot be empty.")
    try:
        gTTS(text=text, lang=get_language_code(language), slow=False).save(str(output_path))
    except Exception as exc:
        logger.exception("Narration generation failed.")
        raise RuntimeError(f"Could not generate narration (gTTS needs internet): {exc}") from exc
    p = Path(output_path)
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError("Narration audio file was not created.")
    return str(p)


# ==================================================
# 6. REAL-WORLD IMAGES  (Pexels / Wikimedia Commons / uploaded picture)
# ==================================================
_STOP = {"a", "an", "the", "of", "in", "on", "and", "with", "for", "to", "close", "up", "view", "photo", "image"}
_BAD_TITLE = ("logo", "icon", "flag of", "signature", "coat of arms", "stamp", "banner", "wordmark", "qr code")


def _http_get(url, timeout=25, headers=None):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def _strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()


def _search_pexels(query, portrait):
    if not PEXELS_API_KEY:
        return []
    qs = urllib.parse.urlencode({"query": query, "per_page": 6,
                                 "orientation": "portrait" if portrait else "landscape"})
    data = json.loads(_http_get("https://api.pexels.com/v1/search?" + qs,
                                headers={"Authorization": PEXELS_API_KEY}))
    out = []
    for p in data.get("photos", []):
        src = p.get("src", {})
        url = src.get("large") or src.get("medium")
        if url:
            out.append((url, f"Photo: {p.get('photographer', 'Pexels')} / Pexels", "Pexels"))
    return out


def _search_commons(query, portrait):
    qs = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280, "format": "json"})
    data = json.loads(_http_get("https://commons.wikimedia.org/w/api.php?" + qs))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP]
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
    return [(u, c, "Wikimedia Commons") for _, _, u, c in ranked[:5] if u]


def _download_image(url, out_path, min_w=500):
    raw = _http_get(url, timeout=40)
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        if im.width < min_w:
            return False
        if max(im.size) > 1600:
            im.thumbnail((1600, 1600))
        im.save(out_path, "JPEG", quality=90)
    return True


def fetch_web_image(query, out_path, portrait=False):
    """Find a real photo for `query`. Returns (credit, source) or None."""
    if not query or not USE_WEB_IMAGES:
        return None
    for search in (_search_pexels, _search_commons):
        try:
            for url, credit, source in search(query, portrait):
                try:
                    if _download_image(url, out_path):
                        return credit, source
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("Image search (%s) failed for %r: %s", search.__name__, query, exc)
    return None


def attach_image(scene, idx, work_dir, portrait, user_image, topic):
    """Sets scene['image_path'] / scene['image_credit'] (None / '' if nothing suitable was found)."""
    scene["image_path"], scene["image_credit"], scene["image_source"] = None, "", ""
    if scene["visual_type"] == "story":
        return
    out = Path(work_dir) / f"photo_{idx}.jpg"
    if scene.get("use_user_image") and user_image:
        try:
            with Image.open(user_image) as im:
                im.convert("RGB").save(out, "JPEG", quality=92)
            scene.update(image_path=str(out), image_credit="Your uploaded image", image_source="Upload")
            return
        except Exception:
            logger.warning("Could not use uploaded image.", exc_info=True)
    q = scene.get("image_query", "").strip()
    if not q or q.upper().startswith("UPLOADED"):
        return
    words = q.split()
    for query in dict.fromkeys([q, " ".join(words[:3]), " ".join(words[:2]), topic]):
        if not query:
            continue
        hit = fetch_web_image(query, out, portrait)
        if hit:
            scene.update(image_path=str(out), image_credit=hit[0], image_source=hit[1])
            return


# ==================================================
# 7. FFMPEG
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


def get_music_track(work_dir, ffmpeg):
    if MUSIC_FILE.is_file():
        return MUSIC_FILE
    pad = Path(work_dir) / "pad.wav"
    run_ffmpeg([
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
        "-f", "lavfi", "-i", "sine=frequency=277.18:sample_rate=44100",
        "-f", "lavfi", "-i", "sine=frequency=329.63:sample_rate=44100",
        "-filter_complex", "[0][1][2]amix=inputs=3:duration=longest,volume=2,tremolo=f=0.25:d=0.4,lowpass=f=900[a]",
        "-map", "[a]", "-t", "30", str(pad)], "music synthesis")
    return pad


def add_background_music(video_path, output_path, work_dir, ffmpeg):
    track = get_music_track(work_dir, ffmpeg)
    run_ffmpeg([
        ffmpeg, "-y", "-i", str(video_path), "-stream_loop", "-1", "-i", str(track),
        "-filter_complex",
        "[0:a]volume=1.0[n];[1:a]volume=0.10[m];"
        "[n][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(output_path)], "background music")
    return str(output_path)


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


class Painter:
    def __init__(self, style, size, language, show_subs, show_hl):
        self.style = style
        self.W, self.H = size
        self.portrait = self.H > self.W
        self.indic = str(language).lower() in ("kannada", "hindi")
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
        self.photo_big = None
        self.photo_size = (10, 10)
        self.photo_pos = (0, 0)
        self.photo_outer = (0, 0, 10, 10)
        self.photo_mask = None
        self.photo_credit = ""
        self.panel = (0, 0, 10, 10)
        self.pan_dir = 1

    # ---------- text ----------
    def text_in_box(self, d, text, box, color, max_size, min_size=16, bold=False, align="center", gap=1.18):
        x0, y0, x1, y1 = box
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
        if scene.get("visual_type") == "photo" and scene.get("image_path"):
            self._load_photo(scene)

    # ---------- photo ----------
    def _load_photo(self, scene):
        x0, y0, x1, y1 = [int(v) for v in self.rect]
        gap = 16
        if self.portrait:
            sy = y0 + int((y1 - y0) * 0.54)
            self.photo_outer = (x0, y0, x1, sy - gap // 2)
            self.panel = (x0, sy + gap // 2, x1, y1)
        else:
            sx = x0 + int((x1 - x0) * 0.60)
            self.photo_outer = (x0, y0, sx - gap // 2, y1)
            self.panel = (sx + gap // 2, y0, x1, y1)
        ox0, oy0, ox1, oy1 = self.photo_outer
        inset = 8
        fw, fh = ox1 - ox0 - 2 * inset, oy1 - oy0 - 2 * inset
        self.photo_size = (fw, fh)
        self.photo_pos = (ox0 + inset, oy0 + inset)
        mask = Image.new("L", (fw, fh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], 18, fill=255)
        self.photo_mask = mask

        with Image.open(scene["image_path"]) as im:
            im = im.convert("RGB")
            bw, bh = int(fw * 1.2), int(fh * 1.2)
            # blurred, darkened "cover" background so any picture shape fills the screen
            cover = max(bw / im.width, bh / im.height)
            bg = im.resize((max(bw, int(im.width * cover)), max(bh, int(im.height * cover))), Image.BILINEAR)
            left, top = (bg.width - bw) // 2, (bg.height - bh) // 2
            bg = bg.crop((left, top, left + bw, top + bh)).filter(ImageFilter.GaussianBlur(14))
            bg = Image.blend(bg, Image.new("RGB", bg.size, (10, 12, 28)), 0.45)
            # the real picture, fully visible (contain) in the middle
            fit = min(fw / im.width, fh / im.height)
            fg = im.resize((max(1, int(im.width * fit)), max(1, int(im.height * fit))), Image.LANCZOS)
            bg.paste(fg, ((bw - fg.width) // 2, (bh - fg.height) // 2))
        self.photo_big = bg
        src = scene.get("image_source") or ""
        self.photo_credit = ("Image: " + src) if src and src != "Upload" else ""

    def _paste_photo(self, img, T):
        fw, fh = self.photo_size
        bw, bh = self.photo_big.size
        p = min(1.0, T / max(0.1, self.total_len))
        e = p * p * (3 - 2 * p)
        z = 1.0 + 0.2 * e                       # slow zoom-in (Ken Burns)
        ww, wh = bw / z, bh / z
        sx, sy = bw - ww, bh - wh
        px = sx * (0.5 + self.pan_dir * 0.35 * (0.5 - e))
        py = sy * 0.5
        crop = self.photo_big.crop((int(px), int(py), int(px + ww), int(py + wh))).resize((fw, fh), Image.BILINEAR)
        img.paste(crop, self.photo_pos, self.photo_mask)
        if self.photo_credit:
            d = ImageDraw.Draw(img)
            f = _font(max(11, int(self.H * .022)), False, False)
            tw = d.textlength(self.photo_credit, font=f)
            bx, by = self.photo_pos[0] + 10, self.photo_pos[1] + fh - int(f.size * 1.9) - 8
            d.rounded_rectangle([bx, by, bx + tw + 16, by + int(f.size * 1.7)], 8, fill=(16, 18, 36))
            d.text((bx + 8, by + int(f.size * .3)), self.photo_credit, font=f, fill=(215, 225, 245))

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
        step = 46
        for gx in range(step // 2, W, step):
            for gy in range(step // 2, H, step):
                dd.ellipse([gx - 2, gy - 2, gx + 2, gy + 2], fill=(255, 255, 255, 24))
        img = Image.alpha_composite(img, dots).convert("RGB")
        self._bg_cache[key] = img
        return img

    def make_particles(self, seed, pal):
        rnd = random.Random(seed * 131 + 7)
        W, H = self.W, self.H
        base = max(8, int(H * 0.012))
        ps = []
        for _ in range(14):
            kind = rnd.choice(["bubble", "bubble", "dot", "star", "star", "plus"])
            r = base * (rnd.uniform(.9, 3.2) if kind == "bubble" else rnd.uniform(.5, 1.6))
            ps.append(dict(kind=kind, x=rnd.random() * W, y=rnd.random() * H, r=r,
                           sp=H * rnd.uniform(.015, .06), amp=W * rnd.uniform(.005, .02),
                           fq=rnd.uniform(.4, 1.2), ph=rnd.uniform(0, 6.28), tw=rnd.uniform(1.2, 3)))
        if pal.get("stars"):
            for _ in range(16):
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
        for wi, (amp, fq, spd, a, yb) in enumerate([(0.012, 2.2, 0.9, .10, .955), (0.016, 1.5, -0.6, .16, .975)]):
            pts = [(0, H)]
            for xx in range(0, W + 1, 32):
                pts.append((xx, H * yb + math.sin(xx / W * math.pi * 2 * fq + T * spd + wi) * H * amp))
            pts.append((W, H))
            d.polygon(pts, fill=tint(H * yb, a, pal["a2"]))

    # ---------- layers ----------
    def _layer(self):
        return Image.new("RGBA", (self.W, self.H), (255, 255, 255, 0))

    def _head_layer(self, scene, scene_no, total, caption, last):
        W, H, pal, m = self.W, self.H, self.pal, self.m
        L = self._layer()
        d = ImageDraw.Draw(L)
        d.rectangle([0, 0, W, 10], fill=(0, 0, 0, 70))
        d.rectangle([0, 0, int(W * (scene_no + 1) / max(1, total)), 10], fill=pal["a1"])
        top, hh = self.top, self.head_h
        d.rounded_rectangle([m, top, m + 12, top + hh], 6, fill=pal["a1"])
        f = _font(max(18, int(H * .03)), True, self.indic)
        counter = f"{scene_no + 1} / {total}"
        cw = d.textlength(counter, font=f)
        d.text((W - m - cw, top + 4), counter, font=f, fill=_mix(WHITE, pal["a2"], .35))
        self.text_in_box(d, scene["title"], (m + 30, top, W - m - cw - 24, top + hh), WHITE,
                         int(H * .075), 24, True, "left")
        if last and self.term_h:
            t0 = (scene.get("key_terms") or [{}])[0]
            ty0 = self.rect[3] + int(H * .015)
            d.rounded_rectangle([m, ty0 + 5, W - m, ty0 + self.term_h + 5], 18, fill=(0, 0, 0, 70))
            d.rounded_rectangle([m, ty0, W - m, ty0 + self.term_h], 18, fill=pal["a1"])
            label = t0.get("term", "")
            if t0.get("definition"):
                label += ": " + t0["definition"]
            self.text_in_box(d, label, (m + 22, ty0 + 4, W - m - 22, ty0 + self.term_h - 4), INK,
                             int(self.term_h * .48), 16, True)
        if self.show_subs and caption:
            sh = self.cap_h - int(H * .03)
            y0 = H - sh - int(H * .025)
            d.rounded_rectangle([m, y0, W - m, y0 + sh], 20, fill=(12, 14, 34, 235), outline=pal["a2"], width=3)
            self.text_in_box(d, caption, (m + 26, y0 + 8, W - m - 26, y0 + sh - 8), WHITE,
                             int(H * (0.05 if not self.portrait else 0.034)), 18)
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
        d.rounded_rectangle([x0 + 6, y0 + 9, x1 + 6, y1 + 9], 22, fill=(0, 0, 0, 70))
        d.rounded_rectangle([x0, y0, x1, y1], 22, fill=WHITE, outline=acc, width=5)
        wide = (x1 - x0) > 3 * (y1 - y0)
        pad = 16
        self.text_in_box(d, text, (x0 + pad, y0 + pad // 2, x1 - pad, y1 - pad // 2), INK,
                         int((y1 - y0) * (.62 if wide else .34)), 16, True)
        self._badge(d, x0 + 6, y0 + 6, 21, idx, number)

    def _arrow(self, d, p1, p2, color):
        d.line([p1, p2], fill=color, width=8)
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        s = 22
        d.polygon([p2, (p2[0] - s * math.cos(ang - .5), p2[1] - s * math.sin(ang - .5)),
                   (p2[0] - s * math.cos(ang + .5), p2[1] - s * math.sin(ang + .5))], fill=color)

    # ---------- diagrams (each draws items[:k]) ----------
    def _draw_photo(self, d, rect, items, k, bubble=False):
        """Classroom-screen frame around the photo + numbered label cards that pop in."""
        ox0, oy0, ox1, oy1 = self.photo_outer
        d.rounded_rectangle([ox0 + 6, oy0 + 9, ox1 + 6, oy1 + 9], 26, fill=(0, 0, 0, 90))
        d.rounded_rectangle([ox0, oy0, ox1, oy1], 26, fill=WHITE, outline=self.pal["a1"], width=4)
        self._draw_list(d, self.panel, items, k)

    def _draw_flow(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        n, gap = len(items), 64
        w, h = x1 - x0, y1 - y0
        col = self.pal["a2"]
        if not self.portrait:
            bw = (w - gap * (n - 1)) / n
            bh = min(h * 0.75, 230)
            ty = y0 + (h - bh) / 2
            for i in range(k):
                bx = x0 + i * (bw + gap)
                self._box(d, [bx, ty, bx + bw, ty + bh], items[i], i, i + 1)
                if i > 0:
                    self._arrow(d, (bx - gap + 8, ty + bh / 2), (bx - 8, ty + bh / 2), col)
        else:
            bh = min((h - gap * (n - 1)) / n, 150)
            ty0 = y0 + (h - (n * bh + (n - 1) * gap)) / 2
            for i in range(k):
                by = ty0 + i * (bh + gap)
                self._box(d, [x0 + 20, by, x1 - 20, by + bh], items[i], i, i + 1)
                if i > 0:
                    cx = (x0 + x1) / 2
                    self._arrow(d, (cx, by - gap + 6), (cx, by - 6), col)

    def _draw_list(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        n = len(items)
        rh = min((y1 - y0) / n - 14, 120)
        ty = y0 + ((y1 - y0) - (n * rh + (n - 1) * 14)) / 2
        for i in range(k):
            by = ty + i * (rh + 14)
            d.rounded_rectangle([x0 + 66, by + 9, x1 + 6, by + rh + 9], 22, fill=(0, 0, 0, 70))
            d.rounded_rectangle([x0 + 60, by, x1, by + rh], 22, fill=WHITE, outline=ACCENTS[i % 6], width=5)
            self.text_in_box(d, items[i], (x0 + 100, by + 6, x1 - 20, by + rh - 6), INK, int(rh * .42), 16, True,
                             "left")
            self._badge(d, x0 + 30, by + rh / 2, rh * .36, i, i + 1)

    def _draw_hub(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        n = max(1, len(items))
        rx, ry = w * 0.36, h * 0.34
        bw = w * .24 if not self.portrait else w * .42
        bh = min(h * .2, 120)
        cr = min(w, h) * .14
        self._hub_center = (cx, cy)
        for i in range(k):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            d.line([(cx, cy), (cx + rx * math.cos(ang), cy + ry * math.sin(ang))], fill=self.pal["a2"], width=7)
        d.ellipse([cx - cr + 5, cy - cr + 8, cx + cr + 5, cy + cr + 8], fill=(0, 0, 0, 70))
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=self.pal["a1"], outline=WHITE, width=6)
        self.text_in_box(d, self.cur.get("title", ""), (cx - cr * .72, cy - cr * .72, cx + cr * .72, cy + cr * .72),
                         INK, int(cr * .5), 14, True)
        for i in range(k):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            px, py = cx + rx * math.cos(ang), cy + ry * math.sin(ang)
            self._box(d, [px - bw / 2, py - bh / 2, px + bw / 2, py + bh / 2], items[i], i)

    def _draw_compare(self, d, rect, items, k, bubble=False):
        x0, y0, x1, y1 = rect
        gap = 60
        cw = (x1 - x0 - gap) / 2
        for side, colr in enumerate((self.pal["a1"], self.pal["a2"])):
            cx0 = x0 + side * (cw + gap)
            d.rounded_rectangle([cx0, y0, cx0 + cw, y0 + 18], 9, fill=colr)
        left = [i for i in range(len(items)) if i % 2 == 0]
        right = [i for i in range(len(items)) if i % 2 == 1]
        rows = max(len(left), len(right), 1)
        rh = min(((y1 - y0 - 40) / rows) - 16, 130)
        for side, col in enumerate((left, right)):
            cx0 = x0 + side * (cw + gap)
            for r, i in enumerate(col):
                if i < k:
                    by = y0 + 40 + r * (rh + 16)
                    self._box(d, [cx0, by, cx0 + cw, by + rh], items[i], i)
        if k >= 2:
            vx, vy = x0 + cw + gap / 2, (y0 + y1) / 2
            d.ellipse([vx - 29, vy - 29, vx + 29, vy + 29], fill=self.pal["a1"], outline=WHITE, width=4)
            f = _font(26, True, False)
            d.text((vx - d.textlength("VS", font=f) / 2, vy - 17), "VS", font=f, fill=INK)

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
        ld.rectangle([tx - 8, g - h * .16, tx + 8, g + 4], fill=(120, 80, 50))
        ld.ellipse([tx - h * .11, g - h * .34, tx + h * .11, g - h * .1], fill=(60, 170, 90))
        rnd = random.Random(5)
        for _ in range(14):
            fx, fy = 20 + rnd.random() * (w - 40), g + h * .06 + rnd.random() * (h * .14)
            ld.ellipse([fx - 5, fy - 5, fx + 5, fy + 5], fill=ACCENTS[rnd.randrange(6)])
        for i in range(len(items)):
            cx = w / 2 + (i - (len(items) - 1) / 2) * 30
            ld.ellipse([cx - 8, h - 26, cx + 8, h - 10], fill=pal["a1"] if i < k else (235, 235, 245))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], 28, fill=255)
        d._image.paste(loc, (x0, y0), mask)
        self._speaker = (k - 1) % 2 if k >= 1 else 0
        bw, bh = w * .62, h * .3
        bx, by = x0 + (w - bw) / 2, y0 + h * .06
        spx = x0 + w * (.22, .72)[self._speaker]
        tail_x = min(max(spx, bx + bw * .15), bx + bw * .85)
        self._story_tip = (spx, y0 + h * .44)
        if bubble and k >= 1:
            d.rounded_rectangle([bx + 6, by + 9, bx + bw + 6, by + bh + 9], 26, fill=(0, 0, 0, 70))
            d.rounded_rectangle([bx, by, bx + bw, by + bh], 26, fill=WHITE, outline=pal["a1"], width=5)
            d.polygon([(tail_x - bw * .05, by + bh - 3), (tail_x + bw * .05, by + bh - 3),
                       (spx, y0 + h * .44)], fill=WHITE)
            self.text_in_box(d, items[k - 1], (bx + 22, by + 12, bx + bw - 22, by + bh - 12), INK,
                             int(bh * .34), 16, True)

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
            d.rounded_rectangle([cx - r * .9, by - r * 2.6, cx + r * .9, by], 20, fill=body)
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
                          output_path, work_dir, ffmpeg, aspect, subtitles):
    W, H = ASPECTS[aspect]
    RW, RH = painter.W, painter.H
    items = scene["visual_items"]
    n_items = len(items)
    steps = split_steps(scene["narration"], n_items)
    weights = [max(1, len(s)) for s in steps]
    durs = [audio_len * x / sum(weights) for x in weights]
    durs[-1] += PAUSE
    total_len = audio_len + PAUSE
    fade = min(0.5, total_len / 4)

    painter.prepare(scene, index - 1, total)
    painter.total_len = total_len

    scale = f"scale={W}:{H}:flags=bicubic," if (RW, RH) != (W, H) else ""
    log_path = Path(work_dir) / f"ffmpeg_scene_{index}.log"
    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-framerate", str(ANIM_FPS),
           "-i", "-", "-i", str(audio_path),
           "-vf", (f"{scale}tpad=stop_mode=clone:stop_duration=2,fade=t=in:st=0:d={fade:.2f},"
                   f"fade=t=out:st={total_len - fade:.2f}:d={fade:.2f},format=yuv420p"),
           "-af", f"apad=pad_dur={PAUSE}",
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
           "-t", f"{total_len:.3f}", "-movflags", "+faststart", str(output_path)]
    with open(log_path, "w", encoding="utf-8", errors="ignore") as logf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=logf, stdout=subprocess.DEVNULL)
        try:
            T, reveal_prev = 0.0, 0
            for j, step_text in enumerate(steps):
                last = j == len(steps) - 1
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
     audio, audio_len, clip, work_dir, ffmpeg) = args
    painter = Painter(style, RENDER_SIZES[aspect], language, subtitles, highlights)
    create_animated_scene(scene, index, total, painter, audio, audio_len,
                          clip, work_dir, ffmpeg, aspect, subtitles)
    return str(clip)


# ==================================================
# 8. FULL PIPELINE
# ==================================================
def generate_video_package(source_text, style="Educational", difficulty="Beginner",
                           language="English", audience="School Students",
                           aspect_ratio="16:9", subtitles=True, highlights=True, music=False,
                           image_path=None, use_web_images=True):
    """
    Returns dict: filename, path, title, duration_seconds, scene_count, script_text, credits.
    image_path: optional uploaded picture that should appear in the video.
    """
    if (not source_text or not source_text.strip()) and image_path:
        source_text = describe_image(image_path)
    if not source_text or not source_text.strip():
        raise ValueError("Please provide educational content.")
    if image_path:
        desc = describe_image(image_path)
        if desc and desc not in source_text:
            source_text = f"{source_text}\n\nUPLOADED PICTURE SHOWS: {desc}"
    raw_style = style
    style = normalize_style(style)
    logger.info("Video style received: %r -> using %r", raw_style, style)
    if aspect_ratio not in ASPECTS:
        raise ValueError("Unsupported aspect ratio.")

    check_ollama_connection()
    ffmpeg = get_ffmpeg_path()
    video_id = uuid.uuid4().hex[:12]
    work_dir = TEMP_DIR / video_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        content = generate_educational_scenes(source_text, style, difficulty, language, audience,
                                              has_user_image=bool(image_path))
        scenes = content["scenes"]
        n = len(scenes)
        portrait = aspect_ratio == "9:16"

        # which scene shows the uploaded picture?
        if image_path:
            flagged = [i for i, s in enumerate(scenes) if s["image_query"].upper().startswith("UPLOADED")]
            for i in (flagged or [0]):
                scenes[i]["use_user_image"] = True

        # ---- 1) narration + real photos for ALL scenes at once (network-bound -> threads) ----
        audios = [work_dir / f"scene_{i}.mp3" for i in range(1, n + 1)]
        topic = content["title"]
        web_ok = bool(use_web_images)
        with ThreadPoolExecutor(max_workers=TTS_WORKERS + 3) as ex:
            tts = [ex.submit(generate_narration, scenes[k]["narration"], audios[k], language) for k in range(n)]
            imgs = []
            for k in range(n):
                if web_ok or scenes[k].get("use_user_image"):
                    imgs.append(ex.submit(attach_image, scenes[k], k + 1, work_dir, portrait, image_path, topic))
                else:
                    scenes[k].update(image_path=None, image_credit="", image_source="")
            for f in tts:
                f.result()
            for f in imgs:
                try:
                    f.result()
                except Exception:
                    logger.warning("Image step failed; scene will use a diagram.", exc_info=True)
        for s in scenes:
            s.setdefault("image_path", None)
            s.setdefault("image_credit", "")
            if s["image_path"] and s["visual_type"] != "story":
                s["visual_type"] = "photo"
        lens = [get_duration(a, ffmpeg) for a in audios]
        if any(x <= 0 for x in lens):
            raise RuntimeError("Could not read narration duration.")
        logger.info("Photos found for %d of %d scenes", sum(1 for s in scenes if s["image_path"]), n)

        clips = [work_dir / f"clip_{i}.mp4" for i in range(1, n + 1)]

        # ---- 2) render every scene ----
        jobs = [(scenes[k], k + 1, n, style, aspect_ratio, language, bool(subtitles), bool(highlights),
                 audios[k], lens[k], clips[k], work_dir, ffmpeg) for k in range(n)]
        workers = max(1, min(MAX_WORKERS, n))
        try:
            if workers > 1:
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    list(ex.map(_render_scene_job, jobs))
            else:
                for job in jobs:
                    _render_scene_job(job)
        except Exception as exc:
            logger.warning("Parallel render failed (%s). Falling back to sequential.", exc)
            for job in jobs:
                if not Path(job[10]).exists() or Path(job[10]).stat().st_size == 0:
                    _render_scene_job(job)

        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", content["title"]).strip("_") or "educational_video"
        final_path = GENERATED_DIR / f"{safe_title[:50]}_{video_id}.mp4"

        if music:
            joined = work_dir / "joined.mp4"
            combine_scene_videos(clips, joined, work_dir, ffmpeg)
            try:
                add_background_music(joined, final_path, work_dir, ffmpeg)
            except Exception:
                logger.warning("Background music failed; using video without music.", exc_info=True)
                shutil.copyfile(joined, final_path)
        else:
            combine_scene_videos(clips, final_path, work_dir, ffmpeg)

        if not final_path.exists():
            raise RuntimeError("Final MP4 video was not created.")

        credits = sorted({s["image_credit"] for s in scenes if s.get("image_credit")})
        return {
            "filename": final_path.name,
            "path": str(final_path),
            "title": content["title"],
            "duration_seconds": int(round(get_duration(final_path, ffmpeg))),
            "scene_count": n,
            "script_text": "\n\n".join(f"{s['title']}\n{s['narration']}" for s in scenes),
            "credits": credits,
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
def generate_quiz(script_text, language="English", difficulty="Beginner", count=5):
    """Returns a list of {question, options[4], correct_index, explanation}."""
    if not script_text or not script_text.strip():
        raise ValueError("No video script is available for this video.")
    prompt = f"""
Create {count} multiple-choice questions that test what a student learned from this lesson.
Use ONLY facts stated in the lesson. Difficulty: {difficulty}. Write in {language}.

LESSON:
{script_text[:MAX_SOURCE_CHARS]}

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