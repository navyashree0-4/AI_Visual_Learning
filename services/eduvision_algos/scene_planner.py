"""
EduVision own algorithm 5: Scene planning.
1. Topic segmentation (TextTiling-style): similarity dips between sliding sentence windows = scene boundaries.
2. Boundaries are adjusted so the number of scenes matches the requested count (merge weakest / split longest).
3. Each scene gets a title (its best concept), key points (summarizer), key terms with definitions, an image query,
   and a suggested visual_type (flow for processes, list for enumerations, compare for contrast, ...).
4. Scenes are ordered intro -> concepts -> recap; the output matches the 'sections' shape used by plan_outline().
"""
import re

from .concept_extraction import extract_concepts
from .summarizer import _cos, _vec, summarize
from .text_preprocessing import preprocess, stem

_PROCESS = re.compile(r"\b(first|then|next|finally|step|process|stage|converted|produces?|leads? to|results? in)\b", re.I)
_LIST = re.compile(r"\b(types?|kinds?|includes?|such as|consists? of|categories|examples?)\b", re.I)
_COMPARE = re.compile(r"\b(unlike|whereas|compared|difference|versus|vs|while|both)\b", re.I)


def _window_vec(stems, i, w=3):
    return _vec([x for s in stems[max(0, i):i + w] for x in s])


def _boundaries(stems, n_scenes):
    n = len(stems)
    if n_scenes <= 1 or n <= n_scenes:
        return list(range(1, n))[: max(0, min(n, n_scenes) - 1)] if n_scenes > 1 else []
    gaps = []  # gap after sentence i (between i and i+1)
    for i in range(n - 1):
        left = _window_vec(stems, i - 2, 3)
        right = _window_vec(stems, i + 1, 3)
        gaps.append((_cos(left, right), i + 1))
    min_size = max(2, n // (n_scenes * 2))
    chosen = []
    for sim, b in sorted(gaps):                      # lowest similarity first
        if len(chosen) == n_scenes - 1:
            break
        if b < min_size or n - b < min_size:
            continue
        if all(abs(b - c) >= min_size for c in chosen):
            chosen.append(b)
    # fill evenly if we could not find enough dips
    step = n / n_scenes
    k = 1
    while len(chosen) < n_scenes - 1 and k < n_scenes:
        cand = int(round(k * step))
        if cand not in chosen and 0 < cand < n:
            chosen.append(cand)
        k += 1
    return sorted(chosen)


def _visual_type(text):
    p, l, c = len(_PROCESS.findall(text)), len(_LIST.findall(text)), len(_COMPARE.findall(text))
    if p >= 2 and p >= l and p >= c:
        return "flow"
    if c >= 2 and c > l:
        return "compare"
    if l >= 1:
        return "list"
    return "list"


def plan_scenes(text, n_scenes=7, topic=None):
    pre = preprocess(text)
    sents, stems = pre["sentences"], pre["stems"]
    if not sents:
        return {"title": topic or "", "sections": []}
    all_concepts = extract_concepts(text, top_k=20, pre=pre)
    n_scenes = max(1, min(n_scenes, len(sents)))
    cuts = [0] + _boundaries(stems, n_scenes) + [len(sents)]
    title = topic or (all_concepts[0]["term"].title() if all_concepts else "Lesson")

    used_titles, sections = set(), []
    for si in range(len(cuts) - 1):
        a, b = cuts[si], cuts[si + 1]
        seg_text = " ".join(sents[a:b])
        seg_pre = {"sentences": sents[a:b], "stems": stems[a:b], "tokens": pre["tokens"][a:b]}
        seg_concepts = [c for c in extract_concepts(seg_text, top_k=6, pre=seg_pre)]
        # prefer globally important concepts that actually occur in this segment
        seg_stems = " ".join(" ".join(s) for s in stems[a:b])
        glob = [c for c in all_concepts if " ".join(stem(w) for w in c["term"].split()) in seg_stems]
        ranked = glob + [c for c in seg_concepts if c["term"] not in {g["term"] for g in glob}]
        # title = concept that is most distinctive for this segment (local count vs. its share of the whole text)
        def distinct(c):
            local = seg_stems.count(" ".join(stem(w) for w in c["term"].split()))
            return local / (1 + c["count"]) + 0.3 * c["score"]
        pool = sorted(ranked, key=distinct, reverse=True)
        name = next((c["term"] for c in pool if c["term"].lower() not in used_titles), None)
        name = (title if si == 0 else (name or f"Part {si + 1}")).title()
        used_titles.add(name.lower())
        if si == 0:
            role = "intro"
        elif si == len(cuts) - 2 and len(cuts) > 3:
            role = "recap"
        else:
            role = "concept"
        points = summarize(seg_text, n_sentences=min(3, b - a), simplify=True, pre=seg_pre, concepts=seg_concepts or None)
        sections.append({
            "title": name,
            "role": role,
            "sentence_range": [a, b],
            "key_points": points,
            "key_terms": [{"term": c["term"], "definition": c["definition"]} for c in ranked[:2]],
            "visual_type": "list" if role == "recap" else _visual_type(seg_text),
            "image_query": (name if name.lower() in title.lower() else f"{title} {name}")[:60] if role != "recap" else "",
            "concepts": [c["term"] for c in ranked[:4]],
        })
    return {"title": title, "sections": sections}
