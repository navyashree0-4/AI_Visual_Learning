"""
EduVision own algorithm 6: Concept validation.
Checks AI-written scenes (Gemini / Ollama) against the student's source text:
  * coverage   - how many of the source's top concepts the script mentions
  * grounding  - per scene, share of content words that appear in the source (or in a small common-word list)
  * unsupported - scene sentences with very low overlap = possible hallucination
  * order      - concepts should be introduced in an order close to the source's order
Returns a report and a pass/fail flag; caller can request a rewrite of weak scenes.
"""
from .concept_extraction import extract_concepts
from .text_preprocessing import preprocess, split_sentences, stem, tokenize


def _stemset(text):
    return {stem(t) for t in tokenize(text)}


def validate_scenes(source_text, scenes, min_coverage=0.6, min_grounding=0.45, top_k=12):
    pre = preprocess(source_text)
    concepts = extract_concepts(source_text, top_k=top_k, pre=pre)
    src_stems = {w for st in pre["stems"] for w in st}
    script = " ".join(" ".join([sc.get("title", ""), sc.get("narration", "")]) for sc in scenes)
    script_stems = _stemset(script)

    covered, missing = [], []
    for c in concepts:
        cs = [stem(w) for w in c["term"].split()]
        (covered if all(w in script_stems for w in cs) else missing).append(c["term"])
    coverage = len(covered) / len(concepts) if concepts else 1.0

    scene_reports, flagged = [], []
    for i, sc in enumerate(scenes):
        words = [stem(t) for t in tokenize(sc.get("narration", ""))]
        if not words:
            continue
        grounded = sum(1 for w in words if w in src_stems) / len(words)
        weak_sents = []
        for s in split_sentences(sc.get("narration", "")):
            ws = [stem(t) for t in tokenize(s)]
            if len(ws) >= 5 and sum(1 for w in ws if w in src_stems) / len(ws) < 0.2:
                weak_sents.append(s)
        scene_reports.append({"index": i, "title": sc.get("title", ""), "grounding": round(grounded, 2),
                              "unsupported_sentences": weak_sents})
        if grounded < min_grounding * 0.5 or len(weak_sents) >= 2:
            flagged.append(i)

    # order check: compare first-mention order of covered concepts in source vs script
    def first_idx(stems_seq, term):
        cs = [stem(w) for w in term.split()]
        for k in range(len(stems_seq) - len(cs) + 1):
            if stems_seq[k:k + len(cs)] == cs:
                return k
        return None
    src_seq = [w for st in pre["stems"] for w in st]
    scr_seq = [stem(t) for t in tokenize(script)]
    pairs = [(first_idx(src_seq, t), first_idx(scr_seq, t)) for t in covered]
    pairs = [p for p in pairs if None not in p]
    inversions = total = 0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            total += 1
            if (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1]) < 0:
                inversions += 1
    order_score = 1 - inversions / total if total else 1.0

    avg_ground = sum(r["grounding"] for r in scene_reports) / len(scene_reports) if scene_reports else 1.0
    return {
        "coverage": round(coverage, 2), "covered": covered, "missing": missing,
        "avg_grounding": round(avg_ground, 2), "order_score": round(order_score, 2),
        "scenes": scene_reports, "flagged_scene_indexes": flagged,
        "passed": coverage >= min_coverage and avg_ground >= min_grounding and not flagged,
    }
