"""
EduVision own algorithms 2 + 3: Concept extraction and keyword/concept ranking.

Candidates = 1-3 word phrases without stopwords at the edges (from preprocessed sentences).
Score = weighted blend of
  * frequency          (stem-merged, sub-linear)
  * TextRank           (PageRank on a word co-occurrence graph, window 4)
  * position           (appears early / in a heading-like first sentence)
  * definition signal  ("X is a", "X refers to", "called X", "X: ...")
  * phrase length bonus (multi-word technical terms beat single generic words)
Redundant phrases (one contained in a better-ranked one) are merged.
"""
import math
import re
from collections import Counter, defaultdict

from .text_preprocessing import STOPWORDS, preprocess, stem, tokenize

_GENERIC_MODIFIERS = {"extra", "more", "other", "many", "various", "several", "different", "main", "simple", "tiny", "small", "large", "new"}

_DEF_PATTERNS = [
    re.compile(r"^(?P<t>[A-Za-z][\w\s\-]{1,40}?)\s+(?:is|are|was|means|refers to|can be defined as)\s+(?:a|an|the|called|known as)?\s*(?P<d>.+)$", re.I),
    re.compile(r"^(?P<t>[A-Za-z][\w\s\-]{1,40}?)\s*[:\u2013\u2014-]\s+(?P<d>.{15,})$"),
    re.compile(r"(?P<d>.+?),?\s+(?:is |are )?(?:called|known as|termed)\s+(?P<t>[A-Za-z][\w\s\-]{1,40}?)(?:[.,;]|$)", re.I),
]


def _candidates(tokens_per_sentence, max_len=3):
    cands = []  # (sentence_index, phrase_tokens)
    for si, toks in enumerate(tokens_per_sentence):
        n = len(toks)
        for i in range(n):
            for L in range(1, max_len + 1):
                if i + L > n:
                    break
                cands.append((si, tuple(toks[i:i + L])))
    return cands


def _textrank(tokens_per_sentence, window=4, d=0.85, iters=30):
    graph = defaultdict(lambda: defaultdict(float))
    for toks in tokens_per_sentence:
        st = [stem(t) for t in toks]
        for i, a in enumerate(st):
            for b in st[i + 1:i + window]:
                if a != b:
                    graph[a][b] += 1
                    graph[b][a] += 1
    if not graph:
        return {}
    score = {n: 1.0 for n in graph}
    out_w = {n: sum(graph[n].values()) for n in graph}
    for _ in range(iters):
        new = {}
        for n in graph:
            new[n] = (1 - d) + d * sum(score[m] * w / out_w[m] for m, w in graph[n].items())
        score = new
    mx = max(score.values())
    return {k: v / mx for k, v in score.items()}


def find_definitions(sentences):
    """Return {lower term: definition sentence}. Used for key_terms in scenes."""
    defs = {}
    for s in sentences:
        for pat in _DEF_PATTERNS:
            m = pat.match(s.strip())
            if m:
                term = m.group("t").strip().lower()
                term = re.sub(r"^(the|a|an)\s+", "", term)
                if 1 <= len(term.split()) <= 4 and not set(term.split()) <= STOPWORDS:
                    defs.setdefault(term, s.strip())
                break
    return defs


def extract_concepts(text, top_k=15, pre=None):
    pre = pre or preprocess(text)
    sents, toks = pre["sentences"], pre["tokens"]
    if not sents:
        return []
    n_sent = len(sents)
    tr = _textrank(toks)
    defs = find_definitions(sents)
    def_terms = {tuple(stem(w) for w in t.split()) for t in defs}

    freq, first_pos, surface = Counter(), {}, defaultdict(Counter)
    for si, phrase in _candidates(toks):
        if phrase[0] in STOPWORDS or phrase[-1] in STOPWORDS:
            continue
        if any(len(w) < 3 for w in phrase) and len(phrase) > 1:
            continue
        if len(phrase) > 1 and (phrase[-1].endswith(("ed", "ly")) or phrase[0] in _GENERIC_MODIFIERS):
            continue                       # "oxygen released", "extra glucose" are not concepts
        key = tuple(stem(w) for w in phrase)
        freq[key] += 1
        first_pos.setdefault(key, si)
        surface[key][" ".join(phrase)] += 1

    max_f = max(freq.values()) if freq else 1
    scored = []
    for key, f in freq.items():
        # multi-word phrases must repeat or be defined, otherwise they're random n-grams
        if len(key) > 1 and f < 2 and key not in def_terms:
            continue
        tr_score = sum(tr.get(w, 0) for w in key) / len(key)
        freq_score = math.log(1 + f) / math.log(1 + max_f)
        pos_score = 1 - first_pos[key] / max(1, n_sent)
        def_score = 1.0 if key in def_terms else 0.0
        len_bonus = {1: 0.0, 2: 0.15, 3: 0.2}[len(key)]
        score = 0.35 * freq_score + 0.30 * tr_score + 0.10 * pos_score + 0.20 * def_score + len_bonus
        scored.append((score, key, f))
    scored.sort(reverse=True)

    chosen = []
    for score, key, f in scored:
        if any(set(key) <= set(c["key"]) or set(c["key"]) <= set(key) for c in chosen):
            # keep the better-ranked (already chosen); skip overlapping variant
            if any(set(key) <= set(c["key"]) for c in chosen):
                continue
        label = surface[key].most_common(1)[0][0]
        term_def = next((v for t, v in defs.items() if tuple(stem(w) for w in t.split()) == key), "")
        chosen.append({"term": label, "key": key, "score": round(score, 4), "count": f,
                       "first_sentence": first_pos[key], "definition": term_def})
        if len(chosen) >= top_k:
            break
    for i, c in enumerate(chosen, 1):
        c["rank"] = i
        c.pop("key")
    return chosen


def rank_keywords(text, top_k=10):
    """Single words only, ranked by the same blend (for tags / image search)."""
    return [c["term"] for c in extract_concepts(text, top_k=top_k * 3) if " " not in c["term"]][:top_k]
