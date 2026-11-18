"""
EduVision own algorithm 7: Algorithmic scene builder (this is what makes the script come from Python, not from AI).

From the student's text it builds complete scenes: title, narration (extracted + simplified sentences from the
source), bullets, key terms with definitions, visual type, visual items and image queries.
No AI is used here. The AI (if enabled) only re-words these scenes afterwards.

Returns None when the text is too short to build a lesson from (for example a bare topic like "photosynthesis");
the caller then falls back to the AI script.
"""
import re

from .concept_extraction import extract_concepts
from .scene_planner import plan_scenes
from .summarizer import summarize
from .text_preprocessing import preprocess
from .topic_understanding import understand_topic

MIN_SENTENCES = 8


def _plain(s):
    s = re.sub(r"\s*\([^)]{0,80}\)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _short(s, words=9):
    s = _plain(s)
    first = re.split(r"[,;:]", s)[0]
    if len(first.split()) >= 4:
        s = first
    w = s.split()
    return " ".join(w[:words]).rstrip(",;:.") if w else ""


def _shorten(sentence, max_words=16):
    """Beginner-friendly: cut a long sentence before a trailing clause. Never leaves a fragment."""
    s = _plain(sentence)
    if len(s.split()) <= max_words:
        return s
    cut = re.search(r",\s+(?:which|where|while|whereas|although|because|so that)\b", s)
    if cut and len(s[:cut.start()].split()) >= 5:
        return s[:cut.start()].rstrip(",;") + "."
    cut = re.search(r";\s+", s)
    if cut and len(s[:cut.start()].split()) >= 5:
        return s[:cut.start()] + "."
    return s


def _pick_sentences(seg_sents, budget_words):
    """Most important sentences of the segment, in original order, until the word budget is filled."""
    seg_text = " ".join(seg_sents)
    chosen, prev, prev_total = seg_sents, None, 0
    for k in range(1, len(seg_sents) + 1):
        chosen = summarize(seg_text, n_sentences=k, simplify=False)
        total = sum(len(x.split()) for x in chosen)
        if total >= budget_words:
            if prev is not None and (total - budget_words) > (budget_words - prev_total):
                chosen = prev                       # the shorter choice is closer to the time budget
            break
        prev, prev_total = chosen, total
    return [_plain(x) for x in chosen]


def build_scenes(text, n_scenes, words_per_scene=60, simple=False):
    pre = preprocess(text)
    sents = pre["sentences"]
    if len(sents) < MIN_SENTENCES:
        return None
    n_scenes = max(4, min(int(n_scenes), len(sents) // 2))
    info = understand_topic(text)                              # step 0: topic, subject, level
    plan = plan_scenes(text, n_scenes=n_scenes - 1, topic=info["topic"])   # last scene is a separate recap
    sections = plan["sections"]
    if len(sections) < 3:
        return None
    title = plan["title"]
    all_concepts = extract_concepts(text, top_k=12, pre=pre)

    scenes = []
    for i, sec in enumerate(sections):
        a, b = sec["sentence_range"]
        seg = sents[a:b]
        facts = _pick_sentences(seg, max(20, words_per_scene - 8))
        if simple:                                             # Simple Explanation style: short sentences
            facts = [_shorten(f) for f in facts]
        lead = f"Let's learn about {title}." if i == 0 else f"Now let's look at {sec['title']}."
        narration = lead + " " + " ".join(facts)
        terms = []
        for kt in sec["key_terms"]:
            d = kt.get("definition") or next((x for x in seg if kt["term"].lower() in x.lower()), "")
            if d:
                terms.append({"term": kt["term"].title(), "definition": _plain(d)})
        items = [c.title()[:40] for c in sec["concepts"]][:4]
        bullets = [_short(f) for f in facts[:3] if _short(f)]
        if len(items) < 2:
            items = [x[:40] for x in bullets][:4]
        scenes.append({
            "title": sec["title"], "explanation": narration, "example": "", "algo_facts": facts,
            "bullets": bullets[:3], "key_terms": terms[:2],
            "visual_type": sec["visual_type"], "visual_items": items,
            "image_query": sec["image_query"] or (sec["title"] if sec["title"].lower() in title.lower() else f"{title} {sec['title']}")[:60],
            "image_query_alt": sec["concepts"][0] if sec["concepts"] else title,
            "example_query": "", "example_label": "",
            "visual_description": f"A picture showing {sec['title'].lower()}",
        })

    key_sents = summarize(text, n_sentences=3, simplify=False, pre=pre)
    if simple:
        key_sents = [_shorten(x) for x in key_sents]
    recap_items = [c["term"].title()[:40] for c in all_concepts[:5]]
    scenes.append({
        "title": "Recap", "explanation": "To recap. " + " ".join(_plain(x) for x in key_sents), "example": "",
        "algo_facts": [_plain(x) for x in key_sents],
        "bullets": [_short(x) for x in key_sents], "key_terms": [],
        "visual_type": "list", "visual_items": recap_items if len(recap_items) >= 2 else ["Key ideas", title],
        "image_query": "", "image_query_alt": "", "example_query": "", "example_label": "",
        "visual_description": "Summary of the key ideas",
    })
    return {"title": title.title(), "scenes": scenes, "topic_info": info}
