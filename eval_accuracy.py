"""
EduVision accuracy evaluation.  Put this file in your project root (next to app.py) and run:

    python eval_accuracy.py                 # script + quiz + language tests (no video rendering)
    python eval_accuracy.py --indic         # Kannada + Hindi only (2 topics each)
    python eval_accuracy.py --video         # also renders a 1-minute video per topic (length + photo + speed)

Needs the same .env as the app (GEMINI_API_KEY or running Ollama).
Writes:  eval_results.csv  (numbers per topic)   and   eval_manual_check.csv  (you mark facts / photos 1 or 0)
"""
import csv
import json
import logging
import re
import sys
import time

from services import video_generator as vg

TOPICS = [
    "Photosynthesis", "Newton's laws of motion", "How the internet works", "The water cycle",
    "Fractions and decimals", "Human digestive system", "What is an algorithm", "Solar system",
]
LANGUAGES = ["English", "Kannada", "Hindi"]
STYLE, DIFFICULTY, AUDIENCE = "Educational", "Beginner", "School Students"
MINUTES = 1
QUIZ_COUNT = 5
DO_VIDEO = "--video" in sys.argv
if "--quick" in sys.argv:                      # 2 topics, English only: finishes fast
    TOPICS, LANGUAGES = TOPICS[:2], ["English"]
if "--indic" in sys.argv:                      # Kannada + Hindi only (2 topics each unless --all-topics)
    LANGUAGES = ["Kannada", "Hindi"]
    if "--all-topics" not in sys.argv:
        TOPICS = TOPICS[:2]
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
print(vg.ai_status() if hasattr(vg, "ai_status") else "AI status not available (old video_generator.py?)", flush=True)


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def ai_answers_quiz(script, quiz):
    """Ask the AI to answer the quiz using ONLY the script. Returns list of chosen indexes."""
    payload = [{"question": q["question"], "options": q["options"]} for q in quiz]
    prompt = f"""
Answer each multiple-choice question using ONLY this lesson.

LESSON:
{script[:9000]}

QUESTIONS:
{json.dumps(payload, ensure_ascii=False)}

Return JSON exactly like this: {{"answers": [0, 2, 1]}}  (one option index 0-3 per question, in order)
"""
    try:
        data = vg.ask_json(prompt, attempts=2, num_predict=600)
        return [int(x) for x in data.get("answers", [])]
    except Exception:
        return []


def main():
    rows, manual = [], []
    for language in LANGUAGES:
        for topic in TOPICS:
            r = {"topic": topic, "language": language}
            print(f"[{len(rows) + 1}/{len(TOPICS) * len(LANGUAGES)}] Starting: {language} / {topic} ...", flush=True)
            t0 = time.time()
            try:
                content = vg.generate_educational_scenes(
                    topic, STYLE, DIFFICULTY, language, AUDIENCE, minutes=MINUTES)
            except Exception as exc:
                r.update(error=f"script failed: {exc}"[:150])
                rows.append(r)
                print(language, topic, "SCRIPT FAILED")
                continue
            r["script_seconds"] = round(time.time() - t0, 1)
            scenes = content["scenes"]
            expected, _ = vg.plan_length(MINUTES, language)
            if vg.FAST_MODE:
                expected = max(3, round(MINUTES * 60 / vg.FAST_SECONDS_PER_SCENE))

            lang_ok = sum(1 for s in scenes if vg._scene_in_language(s, language))
            valid = sum(1 for s in scenes if s["title"] and s["narration"] and len(s["visual_items"]) >= 2)
            r["scenes"] = len(scenes)
            r["language_accuracy_%"] = pct(lang_ok, len(scenes))
            r["structure_accuracy_%"] = pct(min(valid, expected), expected)

            script_text = "\n\n".join(f"{s['title']}\n{s['narration']}" for s in scenes)
            for s in scenes[:3]:
                manual.append({"language": language, "topic": topic, "type": "fact",
                               "item": s["narration"][:300], "correct_1_or_0": ""})

            # quiz
            try:
                quiz = vg.generate_quiz(script_text, language, DIFFICULTY, QUIZ_COUNT)
            except Exception:
                quiz = []
            r["quiz_format_accuracy_%"] = pct(len(quiz), QUIZ_COUNT)
            if quiz:
                ans = ai_answers_quiz(script_text, quiz)
                match = sum(1 for a, q in zip(ans, quiz) if a == q["correct_index"])
                r["quiz_correctness_%"] = pct(match, len(quiz))
                for q in quiz:
                    manual.append({"language": language, "topic": topic, "type": "quiz",
                                   "item": q["question"] + " -> " + q["options"][q["correct_index"]],
                                   "correct_1_or_0": ""})

            # full video (optional)
            if DO_VIDEO:
                t1 = time.time()
                try:
                    res = vg.generate_video_package(topic, STYLE, DIFFICULTY, language, AUDIENCE,
                                                    duration_minutes=MINUTES)
                    secs = time.time() - t1
                    target = MINUTES * 60
                    r["video_seconds_to_make"] = round(secs)
                    r["video_length_s"] = res["duration_seconds"]
                    r["length_accuracy_%"] = round(max(0, 100 - abs(res["duration_seconds"] - target) / target * 100), 1)
                    r["photo_credits_found"] = len(res.get("credits", []))
                    r["voice_engine"] = res.get("voice_engine")
                    manual.append({"language": language, "topic": topic, "type": "photos_match_scene",
                                   "item": res["filename"], "correct_1_or_0": ""})
                except Exception as exc:
                    r["video_error"] = str(exc)[:150]
            rows.append(r)
            print(language, topic, {k: v for k, v in r.items() if k.endswith("%")})

    cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("language", "topic"), k))
    with open("eval_results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open("eval_manual_check.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["language", "topic", "type", "item", "correct_1_or_0"])
        w.writeheader()
        w.writerows(manual)

    print("\n=== AVERAGES ===")
    for key in [c for c in cols if c.endswith("%")]:
        vals = [r[key] for r in rows if key in r]
        if vals:
            print(f"{key:28s} {sum(vals) / len(vals):6.1f}   (n={len(vals)})")
    print("\nNow open eval_manual_check.csv, put 1 (correct) or 0 (wrong) in the last column.")
    print("Fact accuracy % = (number of 1s) / (rows) x 100 for each type.")


if __name__ == "__main__":
    main()