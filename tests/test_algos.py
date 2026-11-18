import json
from services.eduvision_algos.pipeline import analyze, hint_block
from services.eduvision_algos.concept_validator import validate_scenes

TEXT = """Photosynthesis is the process by which green plants make their own food. Plants absorb sunlight using chlorophyll, a green pigment found in chloroplasts. Chloroplasts are present mainly in the leaves of a plant.
Plants take in carbon dioxide from the air through tiny pores called stomata. Roots absorb water from the soil and send it to the leaves through the xylem.
During photosynthesis, chlorophyll captures light energy. This energy is then used to convert carbon dioxide and water into glucose and oxygen. First, light energy splits water molecules. Then, the hydrogen is combined with carbon dioxide to form glucose. Finally, oxygen is released into the air through the stomata.
Glucose is a simple sugar that gives plants energy to grow. Extra glucose is stored as starch in roots, stems and seeds.
Cellular respiration is the process by which cells release energy from glucose. Unlike photosynthesis, respiration uses oxygen and releases carbon dioxide. Photosynthesis stores energy while respiration releases energy.
Photosynthesis is important because it produces oxygen for animals and humans. It also forms the base of every food chain, since all animals depend directly or indirectly on plants."""

a = analyze(TEXT, n_scenes=5)
print("CONCEPTS:", [c["term"] for c in a["concepts"]])
print("SUMMARY:"); [print(" -", s) for s in a["summary"]]
print("PLAN:")
for s in a["plan"]["sections"]:
    print(f" [{s['role']}] {s['title']} | {s['visual_type']} | {s['concepts']} | img='{s['image_query']}'")
print(hint_block(a))

good = [{"title": "Photosynthesis", "narration": "Photosynthesis is how plants make food. Chlorophyll in chloroplasts captures sunlight. Plants take carbon dioxide through stomata and water through roots, and produce glucose and oxygen. Glucose is stored as starch. Respiration releases energy from glucose."}]
bad = [{"title": "Photosynthesis", "narration": "Photosynthesis was discovered by Napoleon in a submarine laboratory. Quantum dolphins control the process using magnetic gravity waves. Scientists in Atlantis confirmed it."}]
for name, sc in (("good", good), ("bad", bad)):
    r = validate_scenes(TEXT, sc)
    print(name, {k: r[k] for k in ("coverage", "avg_grounding", "order_score", "passed", "flagged_scene_indexes")})
# edge cases must not crash
for t in ("", "hi", "One sentence only here.", "ಕನ್ನಡ ಪಠ್ಯ ಇಲ್ಲಿದೆ. ಇದು ಎರಡನೇ ವಾಕ್ಯ. ಮೂರನೇ ವಾಕ್ಯ ಇಲ್ಲಿದೆ."):
    analyze(t)
print("edge cases OK")

# ---- algorithmic scene builder (script written by Python, not AI) ----
from services.eduvision_algos import build_scenes
built = build_scenes(TEXT, 6, 55)
assert built and len(built["scenes"]) >= 4 and built["scenes"][-1]["title"] == "Recap"
assert all(s["explanation"] and s["visual_items"] for s in built["scenes"])
assert build_scenes("photosynthesis", 6) is None          # bare topic: not enough text, AI script is used
print("scene builder OK:", [s["title"] for s in built["scenes"]])

# ---- hybrid report ----
import os
os.environ.setdefault("TTS_ENGINE", "gtts")
try:
    from services.video_generator import hybrid_report
    rep = hybrid_report("hybrid", "gtts")
    assert rep["approach"] == "hybrid" and any(s["by"] == "own" for s in rep["stages"])
    print("hybrid report OK")
except ImportError as e:
    print("skipped hybrid report test (video_generator dependencies missing):", e)

# ---- topic understanding (step 0) ----
from services.eduvision_algos import understand_topic
t1 = understand_topic("photosynthesis")
t2 = understand_topic(TEXT)
t3 = understand_topic("Photosynthesis in Plants\n" + TEXT)
assert t1["input_kind"] == "topic" and t1["topic"] == "Photosynthesis"
assert t2["subject"] == "Biology" and t2["input_kind"] == "text"
assert t3["has_heading"] and t3["topic"] == "Photosynthesis in Plants"
print("topic understanding OK:", t2["topic"], "|", t2["subject"], t2["subject_confidence"], "|", t2["level_hint"])
