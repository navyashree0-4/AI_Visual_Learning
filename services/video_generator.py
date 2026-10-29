import os
import re
import textwrap
import subprocess
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
GENERATED_DIR = BASE_DIR / "static" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = 1280
HEIGHT = 720


def check_ffmpeg():
    """Check whether FFmpeg is installed and available."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise RuntimeError(
            "FFmpeg is not installed or is missing from Windows PATH."
        )


def extract_text(file_path):
    """Extract text from TXT, PDF, or image files."""
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    if extension == ".pdf":
        text = []
        with fitz.open(str(path)) as pdf:
            for page in pdf:
                text.append(page.get_text())
        return "\n".join(text)

    if extension in {".png", ".jpg", ".jpeg"}:
        try:
            import pytesseract
            from PIL import Image

            # If Tesseract is not in PATH, configure its location here:
            # pytesseract.pytesseract.tesseract_cmd = (
            #     r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            # )

            return pytesseract.image_to_string(
                Image.open(path)
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not read the image. Check your Tesseract OCR "
                "installation and image file."
            ) from exc

    raise ValueError(
        "Supported files: PDF, TXT, PNG, JPG, and JPEG."
    )


def create_script(source_text, style, difficulty, language):
    """Use an AI service when configured; otherwise use the supplied text."""
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        # Useful for testing the video pipeline without an API key.
        return source_text[:5000]

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        prompt = f"""
Create a clear educational narration script using the material below.

Video style: {style}
Explanation level: {difficulty}
Narration language: {language}

Requirements:
- Explain the topic accurately in simple spoken language.
- Organize it into a short introduction, key concepts, examples,
  and a conclusion.
- Use approximately 5 to 8 short paragraphs.
- Avoid markdown, tables, and instructions to the video editor.
- Write the narration in the requested language.
- Do not invent facts that are not supported by the source.

Learning material:
{source_text[:12000]}
"""

        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt
        )

        script = response.output_text.strip()

        if not script:
            raise RuntimeError("The AI returned an empty script.")

        return script

    except Exception as exc:
        raise RuntimeError(
            "AI script generation failed. Check your API key, model "
            "access, internet connection, and API usage limits."
        ) from exc


def split_into_scenes(script, max_chars=350):
    """Split the narration into manageable scenes."""
    paragraphs = [
        p.strip() for p in re.split(r"\n+", script)
        if p.strip()
    ]

    scenes = []
    for paragraph in paragraphs:
        pieces = textwrap.wrap(
            paragraph,
            width=max_chars,
            break_long_words=False,
            break_on_hyphens=False
        )
        if pieces:
            scenes.extend(pieces)

    return scenes or ["Welcome to this educational lesson."]


def get_font(size, bold=False):
    """Find a common Windows font, with a default fallback."""
    candidates = []

    if os.name == "nt":
        candidates.append(
            r"C:\Windows\Fonts\arialbd.ttf"
            if bold else r"C:\Windows\Fonts\arial.ttf"
        )

    candidates.extend([
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    ])

    for candidate in candidates:
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size=size)

    return ImageFont.load_default()


def create_slide(text, index, total, output_path, style):
    """Create a 720p educational slide image."""
    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        color=(20, 28, 65)
    )

    draw = ImageDraw.Draw(image)

    # Decorative gradient-like panels.
    draw.rounded_rectangle(
        (45, 45, WIDTH - 45, HEIGHT - 45),
        radius=28,
        fill=(34, 45, 95),
        outline=(111, 117, 255),
        width=3
    )

    title_font = get_font(30, bold=True)
    body_font = get_font(40)
    footer_font = get_font(22)

    draw.text(
        (85, 75),
        "EduVision | Visual Learning",
        font=title_font,
        fill=(151, 220, 255)
    )

    draw.text(
        (85, 125),
        f"Scene {index} of {total}  •  {style}",
        font=footer_font,
        fill=(205, 213, 255)
    )

    # Wrap the content so it fits on the slide.
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        candidate = f"{current_line} {word}".strip()

        if draw.textbbox(
            (0, 0), candidate, font=body_font
        )[2] <= WIDTH - 190:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    line_height = 58
    available_lines = max(1, int(HEIGHT * 0.55 / line_height))
    lines = lines[:available_lines]

    y = 245

    for line in lines:
        draw.text(
            (85, y),
            line,
            font=body_font,
            fill=(255, 255, 255)
        )
        y += line_height

    draw.text(
        (85, HEIGHT - 95),
        "Learn Visually, Learn Better",
        font=footer_font,
        fill=(151, 220, 255)
    )

    image.save(output_path)


def generate_video(source_text, style, difficulty, language):
    """Create a narrated educational MP4 and return its filename."""
    if not source_text or not source_text.strip():
        raise ValueError("No learning material was provided.")

    check_ffmpeg()

    script = create_script(
        source_text,
        style,
        difficulty,
        language
    )

    scenes = split_into_scenes(script)

    # Limit video length and resource usage for this first version.
    scenes = scenes[:15]

    import uuid

    job_id = uuid.uuid4().hex
    work_dir = GENERATED_DIR / f"work_{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    scene_videos = []

    tts_language = "kn" if language.lower() == "kannada" else "en"

    try:
        for index, text in enumerate(scenes, start=1):
            slide_path = work_dir / f"slide_{index:03d}.png"
            audio_path = work_dir / f"audio_{index:03d}.mp3"
            video_path = work_dir / f"scene_{index:03d}.mp4"

            create_slide(
                text,
                index,
                len(scenes),
                slide_path,
                style
            )

            # Requires internet access for Google Text-to-Speech.
            gTTS(
                text=text,
                lang=tts_language
            ).save(str(audio_path))

            # Turn the slide and its narration into a video scene.
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-framerate", "25",
                    "-i", str(slide_path),
                    "-i", str(audio_path),
                    "-vf", "scale=1280:720,format=yuv420p",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-tune", "stillimage",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-shortest",
                    "-movflags", "+faststart",
                    str(video_path)
                ],
                capture_output=True,
                text=True,
                check=True
            )

            scene_videos.append(video_path)

        # Create a concat list for FFmpeg.
        concat_file = work_dir / "concat.txt"

        with open(concat_file, "w", encoding="utf-8") as file:
            for video in scene_videos:
                safe_path = str(video.resolve()).replace("\\", "/")
                safe_path = safe_path.replace("'", r"'\''")
                file.write(f"file '{safe_path}'\n")

        output_name = f"eduvision_{job_id}.mp4"
        output_path = GENERATED_DIR / output_name

        # Combine all scenes into the final educational video.
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output_path)
            ],
            capture_output=True,
            text=True,
            check=True
        )

        return output_name

    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or "")[-1500:]
        raise RuntimeError(
            f"FFmpeg could not finish video generation: {details}"
        ) from exc

    finally:
        # Remove temporary slides, audio, and scene videos.
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
