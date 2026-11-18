"""
EduVision own algorithm 4: Extractive summarization (also used for content simplification).
Sentence score = concept coverage + centrality (similarity to document centroid) + position.
Selection uses MMR so the summary has no near-duplicate sentences.
Simplification: drops parentheticals, trims long sentences at clause boundaries.
"""
import math
import re
from collections import Counter

from .concept_extraction import extract_concepts
from .text_preprocessing import preprocess, stem


def _vec(stems):
    return Counter(stems)


def _cos(a, b):
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0) for k in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def simplify_sentence(s, max_words=22):
    s = re.sub(r"\s*\([^)]{0,80}\)", "", s)
    s = re.sub(r"\b(however|moreover|furthermore|in addition|additionally),?\s+", "", s, flags=re.I)
    words = s.split()
    if len(words) <= max_words:
        return s.strip()
    cut = re.search(r",\s+(?:which|where|while|whereas|although|because|and)\b", s)
    if cut and len(s[:cut.start()].split()) >= 6:
        return s[:cut.start()].rstrip(",;") + "."
    return " ".join(words[:max_words]).rstrip(",;") + "..."


def summarize(text, n_sentences=5, simplify=False, pre=None, concepts=None, lam=0.7):
    pre = pre or preprocess(text)
    sents, stems = pre["sentences"], pre["stems"]
    if len(sents) <= n_sentences:
        return [simplify_sentence(s) if simplify else s for s in sents]
    concepts = concepts or extract_concepts(text, top_k=12, pre=pre)
    cstems = {tuple(stem(w) for w in c["term"].split()): c["score"] for c in concepts}
    centroid = Counter(w for st in stems for w in st)
    vecs = [_vec(st) for st in stems]
    n = len(sents)

    base = []
    for i, st in enumerate(stems):
        joined = " ".join(st)
        cov = sum(sc for k, sc in cstems.items() if " ".join(k) in joined)
        cen = _cos(vecs[i], centroid)
        pos = 1.0 if i == 0 else (0.6 if i < n * 0.2 else 0.3)
        length_pen = 0.0 if 8 <= len(sents[i].split()) <= 35 else -0.25
        base.append(0.45 * cov + 0.35 * cen + 0.20 * pos + length_pen)
    mx = max(base) or 1
    base = [b / mx for b in base]

    chosen = []
    while len(chosen) < n_sentences:
        best, best_val = None, -1e9
        for i in range(n):
            if i in chosen:
                continue
            redundancy = max((_cos(vecs[i], vecs[j]) for j in chosen), default=0.0)
            val = lam * base[i] - (1 - lam) * redundancy
            if val > best_val:
                best, best_val = i, val
        chosen.append(best)
    chosen.sort()                                   # keep original order so it reads naturally
    out = [sents[i] for i in chosen]
    return [simplify_sentence(s) for s in out] if simplify else out
