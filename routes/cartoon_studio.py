"""
routes/cartoon_studio.py  -  AI Cartoon & Animation Studio (blueprint "cartoon")

Pages / API
  GET  /cartoon-studio                          the studio page
  POST /api/cartoon/story                       prompt -> story (Ollama, free)
  POST /api/cartoon/regenerate-scene            rewrite one scene (Ollama, free)
  POST /api/cartoon/generate                    start the animation job (charges credits)
  GET  /api/cartoon/status/<job_id>             live progress + previews + final links
  GET  /cartoon-studio/asset/<job_id>/<name>    character / scene pictures of a running job
  GET  /cartoon-studio/export/<video_id>/<preset>   TikTok / Reels / Shorts / Instagram / YouTube file

It reuses the credit, activity and video-record functions of app.py through app.config
(see the small block added to app.py), and saves the finished movie into the same
`generated_videos` table as educational videos, so it shows up in "My Generated Videos".
"""
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template, request,
    send_file, send_from_directory, session, url_for,
)
from werkzeug.utils import secure_filename

from services import cartoon_generator as cg

cartoon_bp = Blueprint("cartoon", __name__)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = ROOT / "cartoon_work"
GENERATED_DIR = ROOT / "static" / "generated"
EXPORT_DIR = GENERATED_DIR / "exports"
WORK_ROOT.mkdir(parents=True, exist_ok=True)
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Free mode (CARTOON_MODE=free) costs NO credits. Only the paid fal.ai mode charges per scene.
COST_PER_SCENE = 0 if cg.FREE_MODE else max(1, int(os.getenv("CARTOON_CREDITS_PER_SCENE", "5")))
MAX_IMAGE_MB, MAX_AUDIO_MB = 10, 15

JOBS = {}
JOBS_LOCK = threading.Lock()
_ASSET_RE = re.compile(r"^(char|scene)_\d{1,2}\.jpg$")
_ID_RE = re.compile(r"^[a-f0-9]{32}$")


# ------------------------------------------------------------------ helpers
def studio_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Your session expired. Please log in again."), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _hooks():
    """Functions of app.py, registered in app.config. Returns a plain dict (safe to use in threads)."""
    cfg = current_app.config
    keys = ("CHARGE_CREDITS", "REFUND_CREDITS", "GET_USER_CREDITS", "SAVE_VIDEO_RECORD",
            "LOG_ACTIVITY", "BUMP_VIDEO_PROGRESS", "GET_VIDEO_FOR_USER")
    missing = [k for k in keys if k not in cfg]
    if missing:
        raise RuntimeError("app.py is missing the Cartoon Studio hooks: " + ", ".join(missing))
    return {k: cfg[k] for k in keys}


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _opt(value, allowed, default):
    return value if value in allowed else default


def _prune_jobs():
    cutoff = time.time() - 2 * 3600
    with JOBS_LOCK:
        old = [k for k, v in JOBS.items() if v["created"] < cutoff and v["status"] in ("done", "failed")]
        for k in old:
            JOBS.pop(k, None)
    for p in WORK_ROOT.iterdir():
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


# ------------------------------------------------------------------ pages
@cartoon_bp.route("/cartoon-studio")
@studio_login_required
def cartoon_studio():
    hooks = _hooks()
    return render_template(
        "cartoon_studio.html",
        user_name=session.get("user_name", "Student"),
        credits=hooks["GET_USER_CREDITS"](session["user_id"]),
        cost_per_scene=COST_PER_SCENE,
        scenes_by_duration=cg.DURATION_SCENES,
        styles=cg.STYLES,
        presets={k: v[2] for k, v in cg.SOCIAL_PRESETS.items()},
        fal_ready=cg.animation_ready(),
    )


# ------------------------------------------------------------------ story APIs (free, local Ollama)
@cartoon_bp.route("/api/cartoon/story", methods=["POST"])
@studio_login_required
def api_story():
    data = _json_body()
    try:
        story = cg.generate_story(
            data.get("prompt", ""),
            _opt(data.get("style"), cg.STYLES, "3D"),
            _opt(data.get("language"), cg.LANGUAGES, "English"),
            _opt(data.get("duration"), cg.DURATION_SCENES, "Medium"),
        )
        return jsonify(ok=True, story=story)
    except cg.StudioError as exc:
        return jsonify(ok=False, error=str(exc)), 422
    except Exception as exc:
        current_app.logger.exception("Story generation failed")
        return jsonify(ok=False, error=f"Story generation failed: {type(exc).__name__}"), 500


@cartoon_bp.route("/api/cartoon/regenerate-scene", methods=["POST"])
@studio_login_required
def api_regenerate_scene():
    data = _json_body()
    try:
        index = int(data.get("index", -1))
        scene = cg.regenerate_scene(
            data.get("story"), index, data.get("instruction", ""),
            _opt(data.get("style"), cg.STYLES, "3D"),
            _opt(data.get("language"), cg.LANGUAGES, "English"),
        )
        return jsonify(ok=True, scene=scene)
    except (TypeError, ValueError) as exc:
        status = 422 if isinstance(exc, cg.StudioError) else 400
        return jsonify(ok=False, error=str(exc) if isinstance(exc, cg.StudioError) else "Invalid request."), status
    except Exception as exc:
        current_app.logger.exception("Scene regeneration failed")
        return jsonify(ok=False, error=f"Scene regeneration failed: {type(exc).__name__}"), 500


# ------------------------------------------------------------------ animation job
def _save_upload(file, kind, folder):
    if not file or not file.filename:
        return None
    name = secure_filename(file.filename)
    ext = Path(name).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png"} if kind == "image" else {".mp3", ".wav", ".m4a", ".ogg"}
    if ext not in allowed:
        raise cg.StudioError("Image uploads must be JPG, JPEG or PNG; audio uploads MP3, WAV, M4A or OGG.")
    limit = (MAX_IMAGE_MB if kind == "image" else MAX_AUDIO_MB) * 1024 * 1024
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > limit:
        raise cg.StudioError(f"The {kind} file is larger than {limit // 1024 // 1024} MB.")
    dest = Path(folder) / f"upload_{kind}{ext}"
    file.save(str(dest))
    return str(dest)


def _worker(job_id, user_id, story, opts, work_dir, hooks, cost):
    def progress(pct, msg):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job.update(status="running", percent=max(job["percent"], min(99, int(pct))), message=str(msg))

    def asset(kind, index, filename):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job["assets"].append({"kind": kind, "index": index, "name": filename})

    charged, created = cost > 0, None
    try:
        result = cg.generate_movie(
            story, opts["style"], opts["language"], opts["aspect_ratio"], work_dir, GENERATED_DIR, job_id,
            burn_subs=opts["subtitles"], music=opts["music"], sfx=opts["sfx"],
            user_image=opts.get("image"), user_audio=opts.get("audio"),
            progress=progress, asset=asset)
        created = Path(result["path"])

        video_id = hooks["SAVE_VIDEO_RECORD"](user_id, {
            "title": result["title"], "style": f"Cartoon Studio: {opts['style']}",
            "language": opts["language"], "difficulty": "Cartoon", "audience": "Cartoon Studio",
            "aspect_ratio": opts["aspect_ratio"], "filename": result["filename"],
            "duration_seconds": result["duration_seconds"], "subtitles": opts["subtitles"],
            "highlights": False, "music": opts["music"], "script_text": result["script_text"],
        })
        if not video_id:
            raise RuntimeError("The movie was made, but its database record could not be saved.")

        charged, created = False, None
        hooks["LOG_ACTIVITY"](user_id, "video")
        hooks["BUMP_VIDEO_PROGRESS"](user_id)
        minutes, seconds = divmod(int(result["duration_seconds"]), 60)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job.update(status="done", percent=100, message="Your cartoon movie is ready!",
                           result={"video_id": video_id, "filename": result["filename"], "title": result["title"],
                                   "duration": f"{minutes}m {seconds:02d}s", "scenes": result["scene_count"]})
    except Exception as exc:
        if isinstance(exc, cg.StudioError):
            message = str(exc)
        else:
            log.exception("Cartoon generation failed")
            message = f"Cartoon generation failed ({type(exc).__name__}: {str(exc)[:200]})"
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job.update(status="failed", error=message + " Your credits were refunded.")
    finally:
        if charged:
            try:
                hooks["REFUND_CREDITS"](user_id, cost)
            except Exception:
                pass
        if created is not None:
            try:
                created.unlink(missing_ok=True)
            except OSError:
                pass
        # free disk: keep only the small preview pictures
        try:
            for f in Path(work_dir).iterdir():
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                elif f.suffix.lower() != ".jpg" or f.name.startswith("upload_"):
                    f.unlink(missing_ok=True)
        except OSError:
            pass


@cartoon_bp.route("/api/cartoon/generate", methods=["POST"])
@studio_login_required
def api_generate():
    user_id = session["user_id"]
    hooks = _hooks()
    _prune_jobs()

    with JOBS_LOCK:
        for job in JOBS.values():
            if job["user_id"] == user_id and job["status"] in ("queued", "running"):
                return jsonify(ok=False, error="A cartoon is already being made for you. "
                                               "Please wait for it to finish."), 409
    try:
        cg.check_ready()
        try:
            story = cg.sanitize_story(json.loads(request.form.get("story", "")))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, cg.StudioError):
                raise
            raise cg.StudioError("The story could not be read. Generate the story again.") from exc

        opts = {
            "style": _opt(request.form.get("style"), cg.STYLES, "3D"),
            "language": _opt(request.form.get("language"), cg.LANGUAGES, "English"),
            "aspect_ratio": _opt(request.form.get("aspect_ratio"), cg.SIZES, "16:9"),
            "subtitles": request.form.get("subtitles") == "on",
            "music": request.form.get("music") == "on",
            "sfx": request.form.get("sfx") == "on",
        }
        cost = len(story["scenes"]) * COST_PER_SCENE
        if cost > 0 and hooks["GET_USER_CREDITS"](user_id) < cost:
            return jsonify(ok=False, error=f"This movie needs {cost} credits "
                                           f"({len(story['scenes'])} scenes x {COST_PER_SCENE}). "
                                           "Play a learning game to earn more, or choose a shorter movie."), 402

        job_id = uuid.uuid4().hex
        work_dir = WORK_ROOT / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            opts["image"] = _save_upload(request.files.get("image"), "image", work_dir)
            opts["audio"] = _save_upload(request.files.get("audio"), "audio", work_dir)
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise

        if cost > 0 and not hooks["CHARGE_CREDITS"](user_id, cost):
            shutil.rmtree(work_dir, ignore_errors=True)
            return jsonify(ok=False, error=f"You need {cost} credits to make this movie."), 402
    except cg.StudioError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except Exception as exc:
        current_app.logger.exception("Could not start cartoon job")
        return jsonify(ok=False, error=f"Could not start the movie: {type(exc).__name__}"), 500

    with JOBS_LOCK:
        JOBS[job_id] = {"user_id": user_id, "status": "queued", "percent": 1, "message": "Starting",
                        "error": "", "result": None, "assets": [], "created": time.time()}
    threading.Thread(target=_worker, args=(job_id, user_id, story, opts, work_dir, hooks, cost),
                     daemon=True).start()
    session["credits"] = hooks["GET_USER_CREDITS"](user_id)
    return jsonify(ok=True, job_id=job_id, cost=cost, credits=session["credits"])


@cartoon_bp.route("/api/cartoon/status/<job_id>")
@studio_login_required
def api_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        job = json.loads(json.dumps({k: v for k, v in job.items()})) if job else None
    if not job or job["user_id"] != session["user_id"]:
        return jsonify(ok=False, error="This movie job was not found. Check My Generated Videos."), 404

    payload = {
        "ok": True, "status": job["status"], "percent": job["percent"], "message": job["message"],
        "error": job["error"],
        "assets": [{"kind": a["kind"], "index": a["index"],
                    "url": url_for("cartoon.job_asset", job_id=job_id, name=a["name"])} for a in job["assets"]],
    }
    if job["status"] == "done" and job["result"]:
        r = job["result"]
        hooks = _hooks()
        session["credits"] = hooks["GET_USER_CREDITS"](session["user_id"])
        payload["result"] = {
            "title": r["title"], "duration": r["duration"], "scenes": r["scenes"], "credits": session["credits"],
            "video_url": url_for("generated_video_file", filename=r["filename"]),
            "download_url": url_for("download_generated_video", video_id=r["video_id"]),
            "quiz_url": url_for("video_quiz.video_quiz_page", video_id=r["video_id"]),
            "exports": [{"preset": k, "label": v[2],
                         "url": url_for("cartoon.export_video", video_id=r["video_id"], preset=k)}
                        for k, v in cg.SOCIAL_PRESETS.items()],
        }
    return jsonify(payload)


@cartoon_bp.route("/cartoon-studio/asset/<job_id>/<name>")
@studio_login_required
def job_asset(job_id, name):
    if not _ID_RE.match(job_id) or not _ASSET_RE.match(name):
        return ("Not found", 404)
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        owner = job["user_id"] if job else None
    if owner != session["user_id"]:
        return ("Not found", 404)
    return send_from_directory(str(WORK_ROOT / job_id), name, max_age=0)


# ------------------------------------------------------------------ social export
@cartoon_bp.route("/cartoon-studio/export/<int:video_id>/<preset>")
@studio_login_required
def export_video(video_id, preset):
    if preset not in cg.SOCIAL_PRESETS:
        return ("Unknown export format.", 404)
    hooks = _hooks()
    video = hooks["GET_VIDEO_FOR_USER"](video_id, session["user_id"])
    if not video:
        return ("Not found", 404)
    filename = Path(video.get("filename") or "").name
    src = GENERATED_DIR / filename
    if not filename or not src.is_file():
        flash("This video file is no longer available.", "error")
        return redirect(url_for("my_generated_videos"))
    dst = EXPORT_DIR / f"{src.stem}_{preset}.mp4"
    try:
        if not dst.is_file():
            cg.export_for_platform(src, dst, preset)
    except cg.StudioError as exc:
        flash(str(exc), "error")
        return redirect(url_for("cartoon.cartoon_studio"))
    nice = secure_filename(video.get("title") or "cartoon")[:50] or "cartoon"
    return send_file(str(dst), as_attachment=True, download_name=f"{nice}_{preset}.mp4", mimetype="video/mp4")