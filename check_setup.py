"""
Run from your project folder (same place as app.py):   python check_setup.py
Tells you exactly what is missing or broken for video generation.
"""
import sys, os, shutil, subprocess, traceback

def line(ok, msg):
    print(("[ OK ] " if ok else "[FAIL] ") + msg)

print("Python", sys.version.split()[0])
try:
    import PIL
    line(True, "Pillow " + PIL.__version__ + ("" if tuple(int(x) for x in PIL.__version__.split(".")[:2]) >= (9, 2) else "  <- old, run: pip install -U pillow"))
except Exception as e:
    line(False, f"Pillow missing: {e}  -> pip install pillow")

try:
    from services import video_generator as vg
    line(True, "services/video_generator.py imports")
except Exception:
    line(False, "services/video_generator.py failed to import:")
    traceback.print_exc()
    sys.exit(1)

try:
    ff = vg.get_ffmpeg()
    out = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    line(True, "ffmpeg: " + out)
except Exception as e:
    line(False, f"ffmpeg: {e}")
line(bool(vg.get_ffprobe()), "ffprobe found (needed for exact audio length)")
line(vg.edge_tts_available(), "edge-tts installed (needed for the male voice and best quality)")
line(bool(vg.GEMINI_API_KEY), "GEMINI_API_KEY set in .env")
st = vg.ai_status()
print("       AI status:", st)
if not st["available"]:
    line(False, "No AI engine: add GEMINI_API_KEY to .env or start Ollama. Without it the video cannot write a lesson.")

try:
    from PIL import Image
    out_dir = vg.GENERATED_DIR
    sc = {"title": "Test scene", "narration": "This is a test sentence for the caption box. " * 3,
          "labels": ["First point", "Second point", "Third point"], "key_term": {"term": "Test", "definition": "A check."}}
    for ar, (w, h) in vg.ASPECTS.items():
        vg.draw_intro_frame("Setup Test", "English", 1.8, w, h).save(out_dir / f"test_intro_{w}x{h}.jpg")
        r = vg.prepare_renderer(None, sc, 0, 1, w, h, "School Level", "school", "latin")
        r.frame(1.0, 0.5, 0.5).save(out_dir / f"test_scene_{w}x{h}.jpg")
    line(True, f"frame renderer works. Sample frames saved in {out_dir}")
except Exception:
    line(False, "frame renderer crashed:")
    traceback.print_exc()
