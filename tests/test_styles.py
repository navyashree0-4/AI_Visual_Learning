"""Checks that the three video styles are really different. Run from the project root:  python -m tests.test_styles
Needs the generator's normal dependencies (Pillow, gTTS, python-dotenv). No internet, AI or FFmpeg is used."""
import os
import tempfile

from PIL import Image, ImageChops, ImageDraw

from services import video_generator as vg

# 1) every dropdown text ends up as one of THREE styles
assert vg.normalize_style("Educational") == "Educational"
assert vg.normalize_style("Storytelling") == "Storytelling"
assert vg.normalize_style("Animated Storytelling") == "Storytelling"
assert vg.normalize_style("Animated") == "Storytelling"            # old choice still works
assert vg.normalize_style("Simple Explanation") == "Simple Explanation"
assert vg.normalize_style("") == "Educational"

# 2) a story scene keeps its picture query (stories are image based now)
scene = vg._clean_scene({"title": "Drip", "explanation": "Drip rose from the sea.", "image_query": "ocean sunlight",
                         "visual_items": ["a", "b"]}, "Storytelling", True, 0, {"title": "", "image_query": ""})
assert scene["visual_type"] == "story" and scene["image_query"] == "ocean sunlight"

# 3) the same lesson drawn in the three styles gives three clearly different pictures
tmp = tempfile.mkdtemp()
photo = os.path.join(tmp, "p.jpg")
im = Image.new("RGB", (900, 600), (120, 180, 240))
ImageDraw.Draw(im).ellipse([300, 150, 600, 450], fill=(40, 160, 80))
im.save(photo)


def frame(style, vtype):
    p = vg.Painter(style, vg.RENDER_SIZES["16:9"], "English", True, True)
    sc = {"title": "How Plants Make Food", "narration": "Plants make food using sunlight. Roots drink water.",
          "key_terms": [{"term": "Chlorophyll", "definition": "green pigment"}], "visual_type": vtype,
          "visual_items": ["Sunlight hits the leaf", "Roots drink water", "Oxygen is released"],
          "images": [{"path": photo, "credit": "t", "source": "Wikimedia Commons", "kind": "concept", "label": ""}],
          "example_fraction": 0.6}
    p.prepare(sc, 1, 5)
    p.set_photo(0, 0.0, 6.0)
    base, spr = p.build_step(sc, 1, 5, 0, 2, "Plants make food using sunlight.", False)
    return p.render(base, spr, 3.0, 1.0, 3.0)


imgs = {"Educational": frame("Educational", "photo"), "Storytelling": frame("Storytelling", "story"),
        "Simple Explanation": frame("Simple Explanation", "photo")}
names = list(imgs)
for i in range(3):
    for j in range(i + 1, 3):
        diff = ImageChops.difference(imgs[names[i]], imgs[names[j]]).convert("L")
        mean = sum(diff.getdata()) / (diff.width * diff.height)
        assert mean > 12, f"{names[i]} and {names[j]} look too similar (difference {mean:.1f})"
print("video styles OK: three clearly different looks")
