"""
EduVision own algorithm 1: Text preprocessing.
Cleans raw PDF/OCR/typed text, splits sentences, tokenizes, removes stopwords, light stemming.
Works for English; Hindi/Kannada get Unicode-aware tokenizing and sentence splitting (no stopword list).
"""
import re
import unicodedata

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its itself just me more most my no nor not now of off on once only or other our out over own
same she should so some such than that the their theirs them then there these they this those through to too under
until up very was we were what when where which while who whom why will with would you your yours
may might must shall one two three used use using called also thus however therefore etc eg ie
""".split())

_SENT_END = re.compile(r"(?<=[.!?।॥])\s+(?=[A-Z0-9\u0900-\u097F\u0C80-\u0CFF\"'(\[])")
_ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|Dr|Mr|Mrs|Ms|Fig|No|approx|St)\.$", re.I)
_PAGE_NOISE = re.compile(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", re.I)


def clean_text(text):
    """Remove PDF/OCR noise: hyphenated line breaks, page numbers, bullets, repeated spaces."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)             # re-join hyphenated words
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln and not _PAGE_NOISE.match(ln)]
    # merge soft-wrapped lines, keep blank-line paragraph breaks
    out, buf = [], ""
    for ln in lines:
        ln = re.sub(r"^[\u2022\u25CF\u25AA\-\*•]+\s*", "", ln)
        if buf and not re.search(r"[.!?:।॥]$", buf) and not ln[:1].isupper():
            buf += " " + ln
        else:
            if buf:
                out.append(buf)
            buf = ln
    if buf:
        out.append(buf)
    return re.sub(r"[ \t]+", " ", "\n".join(out)).strip()


def _is_heading(line):
    """Short Title-Case / UPPERCASE line without end punctuation, e.g. 'The Water Cycle'."""
    words = line.split()
    if not (1 <= len(words) <= 8) or re.search(r"[.!?:;,\u0964\u0965]$", line.strip()):
        return False
    caps = sum(1 for w in words if w[:1].isupper() or not w[:1].isalpha() or w.lower() in STOPWORDS)
    return caps >= max(1, int(len(words) * 0.8 + 0.5)) and len(words) <= 8 and line[:1].isupper()


def split_sentences(text):
    sentences = []
    paras = re.split(r"\n+", clean_text(text))
    for pi, para in enumerate(paras):
        if pi < len(paras) - 1 and _is_heading(para):
            continue                                   # a heading is not a sentence of the lesson
        parts, cur = _SENT_END.split(para), ""
        for p in parts:
            cur = (cur + " " + p).strip() if cur else p
            if _ABBREV.search(cur):
                continue
            sentences.append(cur)
            cur = ""
        if cur:
            sentences.append(cur)
    return [s for s in (x.strip() for x in sentences) if len(s.split()) >= 3]


def stem(word):
    """Very small suffix stripper, enough to merge 'plants/plant', 'absorbing/absorb'."""
    w = word.lower()
    if not w.isascii() or len(w) <= 4:
        return w
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("edly", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "s" and w.endswith("ss"):
                continue
            return w[: -len(suf)] + rep
    return w


def tokenize(text, keep_stopwords=False):
    toks = re.findall(r"[^\W\d_]+(?:['\-][^\W\d_]+)*|\d+(?:\.\d+)?", (text or "").lower(), flags=re.UNICODE)
    if keep_stopwords:
        return toks
    return [t for t in toks if t not in STOPWORDS and len(t) > 1]


def normalize_tokens(text):
    return [stem(t) for t in tokenize(text)]


def preprocess(text):
    """Returns dict used by every later module."""
    cleaned = clean_text(text)
    sents = split_sentences(cleaned)
    return {
        "clean": cleaned,
        "sentences": sents,
        "tokens": [tokenize(s) for s in sents],
        "stems": [[stem(t) for t in tokenize(s)] for s in sents],
        "word_count": len(cleaned.split()),
    }
