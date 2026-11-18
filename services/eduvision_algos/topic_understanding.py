"""
EduVision own algorithm 0: Topic understanding (the FIRST step of the pipeline).

Given what the student typed or uploaded it works out:
  * input_kind   - "topic" (a few words), "text" (a paragraph) or "document" (long / PDF-like)
  * topic        - the main topic title (heading detection, else the best-ranked concept)
  * subject      - school subject, by a lexicon-based Naive-Bayes-style score over word stems
  * level_hint   - Beginner / Intermediate / Advanced from a readability score (Flesch-Kincaid style)
  * keywords     - top single-word keywords
No AI and no external library is used.
"""
import math
import re

from .concept_extraction import extract_concepts
from .text_preprocessing import preprocess, stem, tokenize

_LEXICON = {
    "Biology": "cell plant animal photosynthesis chlorophyll organism species gene dna protein bacteria virus evolution ecosystem "
               "habitat respiration digestion enzyme tissue organ muscle blood heart brain nerve reproduction fungi stomata glucose oxygen",
    "Physics": "force energy motion velocity acceleration gravity mass newton wave light sound electricity current voltage "
               "magnet pressure heat temperature momentum friction lens optics atom nuclear circuit resistance power work",
    "Chemistry": "atom molecule element compound reaction acid base salt bond ion electron proton metal solution mixture "
                 "periodic oxidation catalyst carbon hydrogen oxygen chemical solvent molecule valency",
    "Mathematics": "number equation algebra geometry triangle circle angle fraction ratio percentage probability statistics "
                   "theorem proof function graph integer prime factor area volume derivative integral matrix",
    "Computer Science": "algorithm program software hardware computer data database network internet code python variable loop "
                        "function memory processor operating system compiler binary encryption artificial intelligence machine learning",
    "History": "war empire king queen dynasty revolution independence ancient medieval colonial treaty battle civilization "
               "emperor freedom movement century culture kingdom republic constitution",
    "Geography": "continent country river mountain climate ocean desert forest population map latitude longitude rainfall "
                 "earthquake volcano soil monsoon plateau island region agriculture resource",
    "Economics & Civics": "economy market trade price demand supply money bank tax government democracy election law "
                          "parliament citizen rights budget inflation poverty business industry",
    "Language & Literature": "poem story novel author character grammar noun verb adjective sentence essay literature "
                             "theme metaphor plot narrator vocabulary paragraph writing",
    "Health": "health disease nutrition vitamin exercise diet hygiene vaccine medicine first aid sleep stress "
              "balanced immunity infection mental fitness",
}
_STEMMED = {sub: {stem(w) for w in words.split()} for sub, words in _LEXICON.items()}


def _syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 1
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups) - (1 if w.endswith("e") and len(groups) > 1 else 0)
    return max(1, n)


def _readability(sentences):
    words = [w for s in sentences for w in re.findall(r"[A-Za-z]+", s)]
    if not words or not sentences:
        return 60.0
    asl = len(words) / len(sentences)
    asw = sum(_syllables(w) for w in words) / len(words)
    return 206.835 - 1.015 * asl - 84.6 * asw          # Flesch reading ease


def _level(score):
    return "Beginner" if score >= 65 else ("Intermediate" if score >= 45 else "Advanced")


def _classify_subject(stems):
    if not stems:
        return "General", 0.0
    counts = {}
    for sub, lex in _STEMMED.items():
        hits = sum(1 for w in stems if w in lex)
        counts[sub] = hits / math.sqrt(len(stems))     # length-normalised hit score
    total = sum(counts.values())
    best = max(counts, key=counts.get)
    if counts[best] == 0 or sum(1 for v in counts.values() if v) == 0:
        return "General", 0.0
    conf = counts[best] / total if total else 0.0
    return (best, round(conf, 2)) if conf >= 0.35 and counts[best] >= 0.15 else ("General", round(conf, 2))


def _heading(text):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) >= 2:
        first = lines[0]
        if len(first.split()) <= 10 and not re.search(r"[.!?]$", first) and len(lines[1].split()) >= 5:
            return re.sub(r"^(topic|title|chapter\s*\d*)\s*[:\-]\s*", "", first, flags=re.I).strip()
    return ""


def understand_topic(text, user_topic=None):
    raw = (text or "").strip()
    pre = preprocess(raw)
    n_words = len(raw.split())
    n_sent = len(pre["sentences"])
    if n_words <= 8 and n_sent <= 1:
        kind = "topic"
    elif n_words < 400 and n_sent < 25:
        kind = "text"
    else:
        kind = "document"

    heading = _heading(raw) if kind != "topic" else ""
    concepts = extract_concepts(raw, top_k=10, pre=pre) if kind != "topic" else []
    if user_topic and str(user_topic).strip():
        topic = str(user_topic).strip()
    elif kind == "topic":
        topic = re.sub(r"[^\w\s&'\-]", " ", raw)
        topic = re.sub(r"\s+", " ", topic).strip()
    elif heading:
        topic = heading
    elif concepts:
        topic = concepts[0]["term"]
    else:
        topic = " ".join(raw.split()[:5])
    topic = topic.title() if topic.islower() or topic.isupper() else topic

    stems = [stem(t) for t in tokenize(raw)]
    subject, conf = _classify_subject(stems)
    return {
        "topic": topic, "input_kind": kind, "has_heading": bool(heading),
        "subject": subject, "subject_confidence": conf,
        "level_hint": _level(_readability(pre["sentences"])) if n_sent >= 2 else "Beginner",
        "keywords": [c["term"] for c in concepts if " " not in c["term"]][:6],
        "word_count": n_words,
    }
