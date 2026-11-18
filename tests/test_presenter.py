"""Checks the Presenter Lesson style. Run from the project root:  python -m tests.test_presenter
Needs Pillow and the generator's normal imports. No internet, AI or FFmpeg is used."""
import os
import tempfile

from PIL import Image, ImageChops, ImageDraw

from services import video_generator as vg

# 1) the style is recognised from any dropdown text, and the other styles are unchanged
for text in ("Presenter", "presenter lesson", "Teacher"):
    assert vg.normalize_style(text) == "Presenter", text
assert vg.normalize_style("Educational") == "Educational"
assert vg.normalize_style("Animated") == "Storytelling"
assert vg.STYLE_KIND["Presenter"] == "present"
assert "Presenter" in vg.STYLE_GUIDE and "Presenter" in vg.STYLE_PALETTES

# 2) a frame is drawn for both screen shapes, with and without a picture
tmp = tempfile.mkdtemp()
photo = os.path.join(tmp, "p.jpg")
im = Image.new("RGB", (800, 500), (30, 40, 90))
ImageDraw.Draw(im).ellipse([300, 150, 500, 350], fill=(240, 190, 90))
im.save(photo)
frames = []
for aspect in ("16:9", "9:16"):
    for voice in ("Female", "Male"):
        painter = vg.Painter("Presenter", vg.RENDER_SIZES[aspect], "English", True, True)
        painter.voice = voice
        for with_photo in (True, False):
            scene = {"title": "Orbits", "narration": "Hello. Planets orbit the Sun.",
                     "visual_type": "photo" if with_photo else "flow",
                     "visual_items": ["Gravity", "Speed", "Orbit"],
                     "key_terms": [{"term": "Orbit", "definition": "a path around a star"}],
                     "images": [{"path": photo, "source": "Test", "kind": "concept"}] if with_photo else []}
            painter.prepare(scene, 0, 2)
            if with_photo:
                painter.set_photo(0, 0, 4)
            base, sprites = painter.build_step(scene, 0, 2, 0, 2, "Planets orbit the Sun.", True)
            frame = painter.render(base, sprites, 1.0, 1.0, 3)
            assert frame.size == (painter.W, painter.H)
            frames.append(frame)

# 3) the presenter really moves (mouth, blink, sway): two moments give different frames
painter = vg.Painter("Presenter", vg.RENDER_SIZES["16:9"], "English", True, True)
a, _, _ = painter._presenter_layer(0.10)
b, _, _ = painter._presenter_layer(0.35)
assert ImageChops.difference(a, b).getbbox(), "presenter does not animate"
print("presenter style OK")
