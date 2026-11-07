
import json
import logging
import re
import shutil
import threading
import time
import uuid

from pathlib import Path
from functools import wraps

from flask import (
    Blueprint, current_app, jsonify, redirect, render_template,
    request, send_file, send_from_directory, session, url_for
)
from werkzeug.utils import secure_filename

from services import cartoon_generator as cg


cartoon_bp = Blueprint("cartoon", __name__)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = ROOT / "cartoon_work"
GENERATED_DIR = ROOT / "static" / "generated"
EXPORT_DIR = GENERATED_DIR / "exports"

for folder in (WORK_ROOT, GENERATED_DIR, EXPORT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

DURATION_COSTS = {
    "Short": 5,
    "Medium": 10,
    "Long": 15,
}

DURATION_SCENES = {
    "Short": 3,
    "Medium": 5,
    "Long": 8,
}

ALLOWED_IMAGES = {".jpg", ".jpeg", ".png"}
ALLOWED_AUDIO = {".mp3", ".wav", ".m4a", ".ogg"}

MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_AUDIO_SIZE = 15 * 1024 * 1024

ID_RE = re.compile(r"^[a-f0-9]{32}$")
ASSET_RE = re.compile(r"^(char|scene)_\d{1,2}\.(jpg|jpeg|png)$")

JOBS = {}
JOBS_LOCK = threading.Lock()


# =========================================================
# AUTHENTICATION
# =========================================================

def login_required(api=False):

    def decorator(function):

        @wraps(function)
        def wrapper(*args, **kwargs):

            if not session.get("user_id"):
                if api:
                    return jsonify(
                        ok=False,
                        error="Please log in first."
                    ), 401

                return redirect(url_for("login"))

            return function(*args, **kwargs)

        return wrapper

    return decorator


# =========================================================
# APP HOOKS
# =========================================================

def get_hooks():

    names = (
        "CHARGE_CREDITS",
        "REFUND_CREDITS",
        "GET_USER_CREDITS",
        "SAVE_VIDEO_RECORD",
        "LOG_ACTIVITY",
        "BUMP_VIDEO_PROGRESS",
        "GET_VIDEO_FOR_USER",
    )

    hooks = {}

    for name in names:
        function = current_app.config.get(name)

        if not callable(function):
            raise RuntimeError(
                f"Missing app.py configuration: {name}"
            )

        hooks[name] = function

    return hooks


def get_balance(hooks, user_id):
    return int(hooks["GET_USER_CREDITS"](user_id) or 0)


def charge(hooks, user_id, amount):

    # Your app.py charge_credits returns True or False.
    return bool(
        hooks["CHARGE_CREDITS"](user_id, amount)
    )


def refund(hooks, user_id, amount):

    try:
        hooks["REFUND_CREDITS"](user_id, amount)
        logger.info(
            "Refunded %s credits to user %s",
            amount,
            user_id,
        )

    except Exception:
        logger.exception(
            "Credit refund failed for user %s",
            user_id,
        )


# =========================================================
# STORY VALIDATION
# =========================================================

def clean_story(value):

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("Invalid story data.")

    if not isinstance(value, dict):
        raise ValueError("Invalid story.")

    story = cg.sanitize_story(value)

    if not isinstance(story, dict):
        raise ValueError("Could not prepare your story.")

    scenes = story.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Your story must contain scenes.")

    if len(scenes) > 14:
        raise ValueError("Too many scenes.")

    return story


def get_duration(story, requested):

    if requested not in DURATION_COSTS:
        requested = story.get("duration", "Medium")

    if requested not in DURATION_COSTS:
        raise ValueError("Invalid video duration.")

    return requested


# =========================================================
# FILE UPLOADS
# =========================================================

def save_upload(file, folder, kind):

    if not file or not file.filename:
        return None

    filename = secure_filename(file.filename)

    if not filename:
        raise ValueError("Invalid uploaded filename.")

    extension = Path(filename).suffix.lower()

    if kind == "image":
        allowed = ALLOWED_IMAGES
        maximum = MAX_IMAGE_SIZE
    else:
        allowed = ALLOWED_AUDIO
        maximum = MAX_AUDIO_SIZE

    if extension not in allowed:
        raise ValueError(
            f"Unsupported {kind} file format."
        )

    data = file.read(maximum + 1)

    if not data:
        raise ValueError("Uploaded file is empty.")

    if len(data) > maximum:
        raise ValueError(
            f"{kind.title()} file exceeds the size limit."
        )

    destination = folder / f"user_{kind}{extension}"
    destination.write_bytes(data)

    return str(destination)


# =========================================================
# JOB MANAGEMENT
# =========================================================

def update_job(job_id, **values):

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if job:
            job.update(values)
            job["updated_at"] = time.time()


def find_job(job_id):

    with JOBS_LOCK:
        return JOBS.get(job_id)


def make_preview_url(job_id, filename):

    return url_for(
        "cartoon.cartoon_asset",
        job_id=job_id,
        name=filename,
    )


# =========================================================
# STUDIO PAGE
# =========================================================

@cartoon_bp.route("/cartoon-studio")
@login_required()
def cartoon_studio():

    hooks = get_hooks()

    return render_template(
        "cartoon_studio.html",
        user_name=session.get("user_name", "Student"),
        credits=get_balance(hooks, session["user_id"]),
        cost_per_scene=0,
        cost_by_duration=DURATION_COSTS,
        duration_costs=DURATION_COSTS,
        scenes_by_duration=DURATION_SCENES,
        styles=getattr(
            cg,
            "STYLES",
            ["3D", "2D Flat", "Anime", "Watercolor"],
        ),
        presets=getattr(cg, "SOCIAL_PRESETS", {}),
        # Local generation is supported; the HTML should not
        # disable generation just because FAL_KEY is absent.
        fal_ready=True,
    )


# =========================================================
# STORY API
# =========================================================

@cartoon_bp.route("/api/cartoon/story", methods=["POST"])
@login_required(api=True)
def api_story():

    try:
        data = request.get_json(silent=True) or {}

        prompt = str(data.get("prompt", "")).strip()
        style = data.get("style", "3D")
        language = data.get("language", "English")
        duration = data.get("duration", "Medium")

        if len(prompt) < 5:
            raise ValueError("Please enter a longer story idea.")

        if duration not in DURATION_SCENES:
            raise ValueError("Invalid duration.")

        if style not in getattr(
            cg, "STYLES",
            ["3D", "2D Flat", "Anime", "Watercolor"]
        ):
            raise ValueError("Invalid cartoon style.")

        if language not in getattr(
            cg, "LANGUAGES",
            ["English", "Kannada", "Hindi"]
        ):
            raise ValueError("Invalid language.")

        story = cg.generate_story(
            prompt,
            style,
            language,
            duration,
        )

        story = clean_story(story)
        story["duration"] = duration

        return jsonify(
            ok=True,
            story=story,
            cost=DURATION_COSTS[duration],
            credits_by_duration=DURATION_COSTS,
        )

    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400

    except Exception:
        logger.exception("Story generation error.")
        return jsonify(
            ok=False,
            error="Could not generate your story."
        ), 500


# =========================================================
# REGENERATE SCENE API
# =========================================================

@cartoon_bp.route(
    "/api/cartoon/regenerate-scene",
    methods=["POST"]
)
@login_required(api=True)
def api_regenerate_scene():

    try:
        data = request.get_json(silent=True) or {}

        story = clean_story(data.get("story"))
        index = int(data.get("index", -1))

        if not 0 <= index < len(story["scenes"]):
            raise ValueError("Invalid scene number.")

        scene = cg.regenerate_scene(
            story,
            index,
            str(data.get("instruction", "")),
            data.get("style", "3D"),
            data.get("language", "English"),
        )

        return jsonify(ok=True, scene=scene)

    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400

    except Exception:
        logger.exception("Scene regeneration error.")
        return jsonify(
            ok=False,
            error="Could not regenerate this scene."
        ), 500


# =========================================================
# GENERATION WORKER
# =========================================================

def generation_worker(
    job_id,
    user_id,
    story,
    options,
    work_dir,
    hooks,
    cost,
):

    charged = True
    final_path = None

    preview_dir = work_dir / "previews"
    preview_dir.mkdir(exist_ok=True)

    def progress(percent, message="Generating video..."):

        try:
            percent = max(0, min(100, int(percent)))
        except (TypeError, ValueError):
            percent = 0

        update_job(
            job_id,
            percent=percent,
            message=str(message),
        )

    def asset(name, path=None):

        # Support callbacks supplied as asset(path) or
        # asset(name, path).
        if path is None:
            path = name
            name = Path(str(path)).name

        name = Path(str(name)).name

        if not ASSET_RE.match(name):
            return

        source = Path(str(path))

        if not source.exists():
            return

        destination = preview_dir / name

        try:
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)

            current = find_job(job_id) or {}
            assets = dict(current.get("assets", {}))
            assets[name] = make_preview_url(job_id, name)

            update_job(job_id, assets=assets)

        except Exception:
            logger.exception("Could not save preview %s", name)

    try:

        progress(5, "Preparing your cartoon...")

        cg.check_ready()

        progress(10, "Creating cartoon scenes...")

        result = cg.generate_movie(
            story=story,
            style=options["style"],
            language=options["language"],
            aspect_ratio=options["aspect_ratio"],
            work_dir=str(work_dir),
            final_dir=str(GENERATED_DIR),
            job_id=job_id,
            burn_subs=options["subtitles"],
            music=options["music"],
            sfx=options["sfx"],
            user_image=options["user_image"],
            user_audio=options["user_audio"],
            progress=progress,
            asset=asset,
        )

        if not isinstance(result, dict):
            raise RuntimeError("Invalid video generator result.")

        filename = secure_filename(
            str(result.get("filename", ""))
        )

        if not filename:
            raise RuntimeError("Generated filename is invalid.")

        final_path = Path(
            result.get("path") or GENERATED_DIR / filename
        ).resolve()

        if final_path.parent != GENERATED_DIR.resolve():
            raise RuntimeError("Invalid generated video location.")

        if not final_path.is_file():
            raise RuntimeError("Generated video file was not found.")

        progress(85, "Saving video to your account...")

        metadata = {
            "title": str(
                result.get("title")
                or story.get("title")
                or "Cartoon Lesson"
            )[:150],
            "style": options["style"],
            "language": options["language"],
            "difficulty": "Beginner",
            "audience": "School Students",
            "aspect_ratio": options["aspect_ratio"],
            "filename": filename,
            "duration_seconds": result.get("duration_seconds", 0),
            "subtitles": options["subtitles"],
            "highlights": True,
            "music": options["music"],
            "script_text": result.get("script_text", ""),
        }

        video_id = hooks["SAVE_VIDEO_RECORD"](
            user_id,
            metadata,
        )

        if not video_id:
            raise RuntimeError(
                "Video could not be saved to My Generated Videos."
            )

        # Saved successfully: the charge is now final.
        charged = False

        try:
            hooks["LOG_ACTIVITY"](user_id, "video")
        except Exception:
            logger.exception("Activity logging failed.")

        try:
            hooks["BUMP_VIDEO_PROGRESS"](user_id)
        except Exception:
            logger.exception("Progress update failed.")

        credits = get_balance(hooks, user_id)

        progress(100, "Your cartoon movie is ready!")

        update_job(
            job_id,
            status="done",
            percent=100,
            result={
                "video_id": video_id,
                "filename": filename,
                "title": metadata["title"],
                "duration": result.get("duration_seconds", 0),
                "scenes": result.get(
                    "scene_count",
                    len(story["scenes"]),
                ),
                "credits": credits,
            },
        )

    except Exception as exc:

        logger.exception("Cartoon job %s failed.", job_id)

        if charged:
            refund(hooks, user_id, cost)

        if final_path and final_path.exists():
            try:
                final_path.unlink()
            except OSError:
                logger.exception("Failed to remove incomplete video.")

        update_job(
            job_id,
            status="failed",
            error=str(exc),
            credits=get_balance(hooks, user_id),
            message="Video generation failed.",
        )

    finally:

        # Keep previews for the preview route.
        # Remove uploaded files and temporary generator files.
        for item in list(work_dir.iterdir()):

            if item.name == "previews":
                continue

            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                logger.exception("Temporary file cleanup failed.")


# =========================================================
# GENERATE API
# =========================================================

@cartoon_bp.route(
    "/api/cartoon/generate",
    methods=["POST"]
)
@login_required(api=True)
def api_generate():

    user_id = session["user_id"]
    charged = False
    work_dir = None

    try:

        hooks = get_hooks()

        with JOBS_LOCK:
            for job in JOBS.values():
                if (
                    job.get("user_id") == user_id
                    and job.get("status") in ("queued", "running")
                ):
                    return jsonify(
                        ok=False,
                        error="A video is already generating."
                    ), 409

        story = clean_story(request.form.get("story", ""))

        duration = get_duration(
            story,
            request.form.get("duration"),
        )

        expected_scenes = DURATION_SCENES[duration]

        if len(story["scenes"]) != expected_scenes:
            raise ValueError(
                f"{duration} videos must contain "
                f"{expected_scenes} scenes. Generate the story again."
            )

        cost = DURATION_COSTS[duration]

        style = request.form.get("style", "3D")
        language = request.form.get("language", "English")

        if style not in getattr(
            cg, "STYLES",
            ["3D", "2D Flat", "Anime", "Watercolor"]
        ):
            raise ValueError("Invalid style.")

        if language not in getattr(
            cg, "LANGUAGES",
            ["English", "Kannada", "Hindi"]
        ):
            raise ValueError("Invalid language.")

        aspect_ratio = request.form.get("aspect_ratio", "16:9")

        if aspect_ratio not in ("16:9", "9:16", "1:1"):
            aspect_ratio = "16:9"

        def checked(name, default=True):
            value = request.form.get(name)
            if value is None:
                return default
            return value.lower() in ("1", "true", "yes", "on")

        balance = get_balance(hooks, user_id)

        if balance < cost:
            return jsonify(
                ok=False,
                error=f"This video costs {cost} credits. Your balance is {balance}.",
                credits=balance,
                cost=cost,
            ), 400

        if not charge(hooks, user_id, cost):
            return jsonify(
                ok=False,
                error="Credit deduction failed. Please try again.",
                credits=get_balance(hooks, user_id),
            ), 400

        charged = True

        job_id = uuid.uuid4().hex
        work_dir = WORK_ROOT / job_id
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            user_image = save_upload(
                request.files.get("image"),
                work_dir,
                "image",
            )

            user_audio = save_upload(
                request.files.get("audio"),
                work_dir,
                "audio",
            )

        except Exception:
            refund(hooks, user_id, cost)
            charged = False
            raise

        options = {
            "style": style,
            "language": language,
            "aspect_ratio": aspect_ratio,
            "subtitles": checked("subtitles"),
            "music": checked("music"),
            "sfx": checked("sfx"),
            "user_image": user_image,
            "user_audio": user_audio,
        }

        with JOBS_LOCK:
            JOBS[job_id] = {
                "user_id": user_id,
                "status": "queued",
                "percent": 0,
                "message": "Starting your video...",
                "error": None,
                "assets": {},
                "result": None,
                "created_at": time.time(),
                "updated_at": time.time(),
            }

        thread = threading.Thread(
            target=generation_worker,
            args=(
                job_id,
                user_id,
                story,
                options,
                work_dir,
                hooks,
                cost,
            ),
            daemon=True,
        )

        try:
            thread.start()
        except Exception:
            with JOBS_LOCK:
                JOBS.pop(job_id, None)
            raise

        charged = False  # Worker now owns the refund responsibility.

        return jsonify(
            ok=True,
            job_id=job_id,
            cost=cost,
            duration=duration,
            credits=get_balance(hooks, user_id),
        )

    except ValueError as exc:

        if charged:
            refund(get_hooks(), user_id, cost)

        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)

        return jsonify(ok=False, error=str(exc)), 400

    except Exception:

        logger.exception("Could not start cartoon generation.")

        if charged:
            try:
                refund(get_hooks(), user_id, cost)
            except Exception:
                logger.exception("Could not refund failed job startup.")

        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)

        return jsonify(
            ok=False,
            error="Could not start video generation."
        ), 500


# =========================================================
# JOB STATUS
# =========================================================

@cartoon_bp.route(
    "/api/cartoon/status/<job_id>"
)
@login_required(api=True)
def api_status(job_id):

    if not ID_RE.match(job_id):
        return jsonify(ok=False, error="Invalid job ID."), 400

    job = find_job(job_id)

    if not job or job["user_id"] != session["user_id"]:
        return jsonify(ok=False, error="Job not found."), 404

    response = {
        "ok": True,
        "status": job["status"],
        "percent": job["percent"],
        "message": job["message"],
        "error": job.get("error"),
        "assets": [
            {
                "url": url,
                "title": name.replace("_", " ").split(".")[0],
            }
            for name, url in job.get("assets", {}).items()
        ],
    }

    if job["status"] == "failed":
        response["credits"] = job.get("credits")

    if job["status"] == "done":

        result = dict(job["result"])
        video_id = result["video_id"]
        filename = result["filename"]

        result["video_url"] = url_for(
            "static",
            filename="generated/" + filename,
        )

        result["download_url"] = url_for(
            "cartoon.download_video",
            video_id=video_id,
        )

        try:
            result["quiz_url"] = url_for(
                "video_quiz.video_quiz_page",
                video_id=video_id,
            )
        except Exception:
            result["quiz_url"] = None

        exports = {}

        for preset in getattr(cg, "SOCIAL_PRESETS", {}):
            exports[preset] = url_for(
                "cartoon.export_video",
                video_id=video_id,
                preset=preset,
            )

        result["exports"] = exports
        response["result"] = result

    return jsonify(response)


# =========================================================
# PREVIEW IMAGE ROUTE
# =========================================================

@cartoon_bp.route(
    "/cartoon-studio/asset/<job_id>/<name>"
)
@login_required()
def cartoon_asset(job_id, name):

    if not ID_RE.match(job_id) or not ASSET_RE.match(name):
        return "Invalid asset", 400

    job = find_job(job_id)

    if not job or job["user_id"] != session["user_id"]:
        return "Asset not found", 404

    folder = WORK_ROOT / job_id / "previews"

    if not (folder / name).is_file():
        return "Preview not found", 404

    return send_from_directory(str(folder), name)


# =========================================================
# VIDEO DOWNLOAD
# =========================================================

@cartoon_bp.route(
    "/cartoon-studio/download/<int:video_id>"
)
@login_required()
def download_video(video_id):

    hooks = get_hooks()

    record = hooks["GET_VIDEO_FOR_USER"](
        video_id,
        session["user_id"],
    )

    if not record:
        return "Video not found", 404

    filename = secure_filename(
        str(record.get("filename", ""))
    )

    if not filename:
        return "Invalid video filename", 400

    path = GENERATED_DIR / filename

    if not path.is_file():
        return "Video file not found", 404

    return send_file(
        path,
        as_attachment=True,
        download_name=filename,
        mimetype="video/mp4",
    )


# =========================================================
# SOCIAL MEDIA EXPORT
# =========================================================

@cartoon_bp.route(
    "/cartoon-studio/export/<int:video_id>/<preset>"
)
@login_required()
def export_video(video_id, preset):

    try:

        hooks = get_hooks()

        presets = getattr(cg, "SOCIAL_PRESETS", {})

        if preset not in presets:
            return "Invalid export preset", 400

        record = hooks["GET_VIDEO_FOR_USER"](
            video_id,
            session["user_id"],
        )

        if not record:
            return "Video not found", 404

        filename = secure_filename(
            str(record.get("filename", ""))
        )

        source = GENERATED_DIR / filename

        if not source.is_file():
            return "Source video not found", 404

        output_name = (
            f"{Path(filename).stem}_{secure_filename(preset)}.mp4"
        )

        destination = EXPORT_DIR / output_name

        if not destination.is_file():

            cg.export_for_platform(
                str(source),
                str(destination),
                preset,
            )

        if not destination.is_file():
            return "Export could not be created", 500

        return send_file(
            destination,
            as_attachment=True,
            download_name=output_name,
            mimetype="video/mp4",
        )

    except Exception:
        logger.exception("Social export failed.")
        return "Could not export this video.", 500
