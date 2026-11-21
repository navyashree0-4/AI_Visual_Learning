"""
ai_images.py  --  EduVision: AI-made REAL-LOOKING photographs for video scenes (Gemini image model).

SAVE AS:  services/ai_images.py

No stock website is needed. Each scene gets a photorealistic picture generated from its description.
Uses the same GEMINI_API_KEY as the rest of EduVision.

.env (all optional)
    GEMINI_API_KEY=...                       required for AI pictures
    GEMINI_IMAGE_MODEL=gemini-2.5-flash-image   change if Google renames the model
    AI_IMAGE_WORKERS=3                       how many pictures are made at the same time
    AI_IMAGE_TIMEOUT=60                      seconds to wait for one picture

generate_scene_image(query, title, topic, out_path, portrait, style="photo"|"animation") -> True when a JPEG was saved, else False.
It never raises: on any problem it returns False so the caller can use another source.
After 4 failures in a row it pauses for 5 minutes so a quota / key problem does not slow every video.
"""
import base64
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from PIL import Image

logger = logging.getLogger("quick_video")

API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
TIMEOUT = max(10, int(os.getenv("AI_IMAGE_TIMEOUT", "60") or 60))
_sem = threading.Semaphore(max(1, int(os.getenv("AI_IMAGE_WORKERS", "3") or 3)))
_lock = threading.Lock()
_fails = 0
_pause_until = 0.0


def _key():
    return os.getenv("GEMINI_API_KEY", "").strip()


def available():
    return bool(_key()) and time.time() >= _pause_until


def _note(ok):
    global _fails, _pause_until
    with _lock:
        if ok:
            _fails = 0
            return
        _fails += 1
        if _fails >= 4:
            _pause_until = time.time() + 300
            _fails = 0
            logger.warning("AI pictures failed 4 times in a row; pausing them for 5 minutes.")


def _prompt(query, title, topic, style="photo"):
    if str(style).lower().startswith("anim"):
        return (f"A colourful, high-quality 3D animated style illustration (like a modern animated film) of {query}. "
                f"It illustrates the lesson topic '{topic}', scene '{title}'. Clean friendly design, bright colours, "
                "soft lighting, the subject clearly shown. Show objects, places and nature; no people or characters "
                "unless the subject itself is a person. Absolutely no text, no letters, no numbers, no words in any "
                "language, no logos, no watermark, no captions.")
    return (f"A realistic photograph of {query}. It illustrates the lesson topic '{topic}', scene '{title}'. "
            "Real camera photo, natural lighting, sharp focus, professional documentary photography. "
            "Absolutely no text, no letters, no logos, no watermark, no captions. "
            "Not a cartoon, not an illustration, not a drawing, not clipart, not 3D render, no mascot or character.")


def _call(prompt, aspect):
    cfg = {"responseModalities": ["IMAGE"]}
    if aspect:
        cfg["imageConfig"] = {"aspectRatio": aspect}
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
    req = urllib.request.Request(f"{API_BASE}/models/{MODEL}:generateContent",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _extract(data):
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                return base64.b64decode(blob["data"])
    return None


def generate_scene_image(query, title, topic, out_path, portrait=False, style="photo"):
    if not available() or not str(query or "").strip():
        return False
    aspect = "9:16" if portrait else "16:9"
    prompt = _prompt(str(query).strip()[:120], str(title or "")[:80], str(topic or "")[:120], style)
    with _sem:
        try:
            try:
                data = _call(prompt, aspect)
            except urllib.error.HTTPError as exc:
                if exc.code == 400:                       # model without aspect-ratio support: ask again without it
                    data = _call(prompt, None)
                else:
                    raise
            raw = _extract(data)
            if not raw:
                raise RuntimeError("the model returned no picture")
            with Image.open(io.BytesIO(raw)) as im:
                im = im.convert("RGB")
                if im.width < 480 or im.height < 270:
                    raise RuntimeError("picture too small")
                if max(im.size) > 1600:
                    im.thumbnail((1600, 1600), Image.LANCZOS)
                im.save(out_path, "JPEG", quality=92)
            _note(True)
            return True
        except Exception as exc:
            logger.warning("AI picture failed: %s", str(exc)[:160])
            _note(False)
            return False
