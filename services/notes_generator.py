"""
notes_generator.py  --  EXAM NOTES + QUESTION ANSWERING from the student's OWN PDF / TXT / pasted text.

SAVE THIS FILE AS:  services/notes_generator.py

    make_notes(source, topic, language, detail)  -> dict with title, summary, sections, terms, formulas,
                                                    questions, quick_revision, blocks (ready to show), mode
    notes_to_text(notes)                         -> plain text (.txt download / copy button)
    notes_to_pdf(notes)                          -> PDF bytes
    answer_question(source, question, language, history) -> {"found": bool, "answer": str}

Rules:
    * Everything comes ONLY from the document the student gave. Nothing from outside is added.
    * Long documents are cut into parts, every part is summarised (so nothing is skipped), then merged.
    * Works with an AI model (Gemini / Ollama, same settings as the video generator).
      Without any AI model: English notes and answers are made with a built-in extractive algorithm.

PDF: English uses reportlab (pip install reportlab).  Kannada / Hindi pages are drawn with Pillow and need a
Kannada / Devanagari font (Nirmala UI on Windows, Noto Sans on Linux), the same one the video generator uses.
"""
import io
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

from services.video_generator import (
    LANG_KEYS, LANGUAGE_NOTE, SCRIPT_RANGES, _STOP, _SCRATCH, _find_font, _font, _wrap, ai_available, ask_json,
)

logger = logging.getLogger("quick_video")

CHUNK_CHARS = 7000          # one part of the document sent to the AI at a time
LANGS = list(LANG_KEYS.values())
DETAIL = {
    "quick": dict(points=6, terms=10, questions=5, revision=8, label="Quick revision notes"),
    "detailed": dict(points=12, terms=22, questions=10, revision=12, label="Detailed revision notes"),
}
LABELS = {
    "English": dict(summary="Summary", key="Key points", terms="Important terms", formulas="Formulas",
                    questions="Likely exam questions", revision="Last-minute revision",
                    meta="Made only from your document"),
    "Hindi": dict(summary="सारांश", key="मुख्य बिंदु", terms="महत्वपूर्ण शब्द", formulas="सूत्र",
                  questions="संभावित परीक्षा प्रश्न", revision="अंतिम समय की दोहराई",
                  meta="केवल आपके दस्तावेज़ से बनाया गया"),
    "Kannada": dict(summary="ಸಾರಾಂಶ", key="ಮುಖ್ಯ ಅಂಶಗಳು", terms="ಪ್ರಮುಖ ಪದಗಳು", formulas="ಸೂತ್ರಗಳು",
                    questions="ಸಂಭಾವ್ಯ ಪರೀಕ್ಷಾ ಪ್ರಶ್ನೆಗಳು", revision="ಕೊನೆಯ ಕ್ಷಣದ ಪುನರಾವರ್ತನೆ",
                    meta="ನಿಮ್ಮ ದಾಖಲೆಯಿಂದ ಮಾತ್ರ ತಯಾರಿಸಲಾಗಿದೆ"),
}
NOT_FOUND = {
    "English": "This is not mentioned in your document.",
    "Hindi": "यह आपके दस्तावेज़ में नहीं बताया गया है।",
    "Kannada": "ಇದು ನಿಮ್ಮ ದಾಖಲೆಯಲ್ಲಿ ಉಲ್ಲೇಖಿಸಲಾಗಿಲ್ಲ.",
}


def _ws(v):
    """Whitespace clean only (keeps formulas such as x_1, [A], a*b untouched)."""
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _pick_language(language):
    t = str(language or "").strip().lower()
    for lang in LANGS:
        if t == lang.lower() or lang.lower() in t:
            return lang
    return "English"


def _shorten(s, limit=220):
    s = _ws(s)
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def _sentences(text):
    out = []
    for part in re.split(r"(?<=[.!?।])\s+|\n+", str(text or "")):
        part = _ws(part)
        if 5 <= len(part.split()) <= 45:
            out.append(part)
    return out


def split_chunks(text, size=CHUNK_CHARS):
    """Cut the document into parts of about `size` characters at line / paragraph borders."""
    text = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    chunks, cur = [], ""
    for p in [p.strip() for p in text.split("\n") if p.strip()]:
        while len(p) > size:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:size])
            p = p[size:]
        if cur and len(cur) + len(p) + 1 > size:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n" + p).strip()
    if cur:
        chunks.append(cur)
    return chunks


# ==================================================
# 1. NOTES WITH AN AI MODEL (part by part, then merged)
# ==================================================
def _chunk_notes(i, n, text, language, detail):
    d = DETAIL[detail]
    prompt = f"""
Make EXAM REVISION NOTES from part {i + 1} of {n} of a student's document.
Use ONLY the document text below. Do NOT add outside facts, examples or explanations. If something is not in the text, leave it out.
LANGUAGE: {language}. {LANGUAGE_NOTE[language.lower()]}

Rules:
- points: at most {d['points']} short revision bullet points, each at most 22 words, in the order of the text. Keep numbers, names, dates and formulas exactly as written.
- terms: important terms that the text defines (definition must come from the text). Empty list if none.
- formulas: only formulas / equations that appear in the text. Empty list if none.
- questions: {max(2, d['questions'] // 2)} likely exam questions with short answers taken from the text.
- heading: a short heading (max 8 words) for this part.

DOCUMENT TEXT:
{text}

Return JSON exactly like this:
{{"heading": "...", "points": ["..."], "terms": [{{"term": "...", "definition": "..."}}],
  "formulas": ["..."], "questions": [{{"q": "...", "a": "..."}}]}}
"""
    data = ask_json(prompt)
    points = [_ws(x)[:300] for x in (data.get("points") or []) if _ws(x)][:d["points"]]
    if not points:
        raise ValueError("no points")
    terms, questions = [], []
    for t in data.get("terms") or []:
        if isinstance(t, dict) and _ws(t.get("term")) and _ws(t.get("definition")):
            terms.append({"term": _ws(t["term"])[:60], "definition": _ws(t["definition"])[:260]})
    for q in data.get("questions") or []:
        if isinstance(q, dict) and _ws(q.get("q")) and _ws(q.get("a")):
            questions.append({"q": _ws(q["q"])[:240], "a": _ws(q["a"])[:360]})
    return {"heading": _ws(data.get("heading"))[:80] or f"Part {i + 1}", "points": points, "terms": terms,
            "formulas": [_ws(x)[:160] for x in (data.get("formulas") or []) if _ws(x)], "questions": questions}


def _overview(sections, topic, language, detail):
    d = DETAIL[detail]
    body = "\n".join(f"{s['heading']}: " + " | ".join(s["points"]) for s in sections)[:9000]
    prompt = f"""
Below are revision notes made from a student's document{(' about ' + topic) if topic else ''}.
Using ONLY these notes write:
- title: a short title of the document (max 10 words)
- summary: 3 to 4 sentences summarising the whole document
- quick_revision: exactly {d['revision']} one-line facts a student must remember the night before the exam
LANGUAGE: {language}. {LANGUAGE_NOTE[language.lower()]}

NOTES:
{body}

Return JSON: {{"title": "...", "summary": "...", "quick_revision": ["..."]}}
"""
    data = ask_json(prompt)
    rev = [_ws(x)[:240] for x in (data.get("quick_revision") or []) if _ws(x)][:d["revision"]]
    return _ws(data.get("title"))[:120], _ws(data.get("summary"))[:900], rev


def _merge(parts, detail):
    d = DETAIL[detail]
    sections, terms, formulas, questions = [], [], [], []
    seen_t, seen_f = set(), set()
    for p in parts:
        sections.append({"heading": p["heading"], "points": p["points"]})
        for t in p["terms"]:
            if t["term"].lower() not in seen_t:
                seen_t.add(t["term"].lower())
                terms.append(t)
        for f in p["formulas"]:
            if f not in seen_f:
                seen_f.add(f)
                formulas.append(f)
        questions += p["questions"]
    return sections, terms[:d["terms"]], formulas[:20], questions[:d["questions"]]


def _notes_ai(chunks, topic, language, detail):
    def one(args):
        i, ch = args
        try:
            return _chunk_notes(i, len(chunks), ch, language, detail)
        except Exception as exc:
            logger.warning("Notes part %s failed: %s", i + 1, str(exc)[:120])
            return None

    with ThreadPoolExecutor(max_workers=3) as ex:
        parts = [p for p in ex.map(one, list(enumerate(chunks))) if p]
    if not parts:
        raise RuntimeError("The AI could not make notes from this document.")
    sections, terms, formulas, questions = _merge(parts, detail)
    try:
        title, summary, rev = _overview(sections, topic, language, detail)
    except Exception as exc:
        logger.warning("Notes overview failed: %s", str(exc)[:120])
        title, summary, rev = "", "", []
    flat = [p for s in sections for p in s["points"]]
    return {"title": title or topic or "Study notes",
            "summary": summary or " ".join(flat[:3]),
            "sections": sections, "terms": terms, "formulas": formulas, "questions": questions,
            "quick_revision": rev or flat[:DETAIL[detail]["revision"]]}


# ==================================================
# 2. NOTES WITHOUT ANY AI MODEL (English, extractive)
# ==================================================
_TERM_RE = re.compile(r"^([A-Z][A-Za-z0-9\-' ]{2,40}?) (?:is|are|means|refers to|is defined as) (.{15,220})$")


def _words(s):
    return [w for w in re.findall(r"[a-z][a-z\-]{3,}", s.lower()) if w not in _STOP]


def _notes_algo(chunks, topic, detail):
    d = DETAIL[detail]
    freq = Counter(w for ch in chunks for w in _words(ch))
    per = max(3, d["points"] // 2)
    sections, terms, formulas, ranked_all = [], [], [], []
    seen_t, seen_s = set(), set()
    for i, ch in enumerate(chunks):
        sents = []
        for s0 in _sentences(ch):                     # the same sentence is never used twice
            if s0.lower() not in seen_s:
                seen_s.add(s0.lower())
                sents.append(s0)
        scored = [(sum(freq[w] for w in set(_words(s))) / (len(s.split()) ** 0.6), k, s) for k, s in enumerate(sents)]
        top = sorted(scored, reverse=True)[:per]
        ranked_all += top
        points = [_shorten(s) for _, _, s in sorted(top, key=lambda x: x[1])]
        first = _ws(ch.split("\n", 1)[0])
        heading = first if (1 <= len(first.split()) <= 8 and not first.endswith(".")) else \
            ("Main points" if len(chunks) == 1 else f"Part {i + 1}")
        if points:
            sections.append({"heading": heading[:80], "points": points})
        for s in sents:
            m = _TERM_RE.match(s)
            if m and len(m.group(1).split()) <= 5 and m.group(1).lower() not in seen_t:
                seen_t.add(m.group(1).lower())
                terms.append({"term": m.group(1), "definition": _shorten(m.group(2), 240)})
        for line in ch.split("\n"):
            line = _ws(line)
            if "=" in line and len(line.split()) <= 12 and len(line) <= 90 and line not in formulas:
                formulas.append(line)
    if not sections:
        raise RuntimeError("Not enough readable sentences to make notes.")
    best = [s for _, _, s in sorted(ranked_all, reverse=True)]
    summary = " ".join(_shorten(s, 200) for s in best[:3])
    questions = [{"q": f"What is {t['term']}?", "a": t["definition"]} for t in terms[:d["questions"]]]
    first_line = _ws(chunks[0].split("\n", 1)[0])
    doc_title = first_line if (1 <= len(first_line.split()) <= 10 and not first_line.endswith(".")) else "Study notes"
    return {"title": topic or doc_title, "summary": summary, "sections": sections,
            "terms": terms[:d["terms"]], "formulas": formulas[:20], "questions": questions,
            "quick_revision": [_shorten(s, 200) for s in best[:d["revision"]]]}


# ==================================================
# 3. PUBLIC: make notes / text / blocks
# ==================================================
def build_blocks(n):
    """Flat list the page shows and the TXT / PDF writers print: [{"t": type, "a": str, "b": str}]."""
    L = LABELS.get(n.get("language"), LABELS["English"])
    label = DETAIL[n.get("detail", "quick")]["label"]
    B = [{"t": "title", "a": n["title"]}, {"t": "meta", "a": f"{label} · {L['meta']}"}]
    if n["summary"]:
        B += [{"t": "h", "a": L["summary"]}, {"t": "p", "a": n["summary"]}]
    if n["sections"]:
        B.append({"t": "h", "a": L["key"]})
        for s in n["sections"]:
            B.append({"t": "h2", "a": s["heading"]})
            B += [{"t": "b", "a": p} for p in s["points"]]
    if n["terms"]:
        B.append({"t": "h", "a": L["terms"]})
        B += [{"t": "kv", "a": t["term"], "b": t["definition"]} for t in n["terms"]]
    if n["formulas"]:
        B.append({"t": "h", "a": L["formulas"]})
        B += [{"t": "b", "a": f} for f in n["formulas"]]
    if n["questions"]:
        B.append({"t": "h", "a": L["questions"]})
        B += [{"t": "qa", "a": q["q"], "b": q["a"]} for q in n["questions"]]
    if n["quick_revision"]:
        B.append({"t": "h", "a": L["revision"]})
        B += [{"t": "b", "a": x} for x in n["quick_revision"]]
    return B


def make_notes(source, topic="", language="English", detail="quick"):
    source = re.sub(r"\n{3,}", "\n\n", str(source or "")).strip()
    if len(source.split()) < 40:
        raise ValueError("The file has too little text to make notes from (at least about 40 words are needed).")
    language = _pick_language(language)
    detail = "detailed" if detail == "detailed" else "quick"
    topic = _ws(topic)[:150]
    chunks = split_chunks(source)
    notes, mode = None, "ai"
    if ai_available():
        try:
            notes = _notes_ai(chunks, topic, language, detail)
        except Exception as exc:
            logger.warning("AI notes failed (%s). Using the built-in algorithm.", str(exc)[:160])
    if notes is None:
        if language != "English":
            raise RuntimeError(f"Notes in {language} need an AI model (set GEMINI_API_KEY or start Ollama).")
        notes, mode = _notes_algo(chunks, topic, detail), "algorithm"
    notes.update(language=language, detail=detail, mode=mode)
    notes["blocks"] = build_blocks(notes)
    return notes


def notes_to_text(n):
    out = []
    for b in n["blocks"]:
        t = b["t"]
        if t == "title":
            out += [b["a"].upper(), "=" * min(70, len(b["a"])), ""]
        elif t == "meta":
            out += [b["a"], ""]
        elif t == "h":
            out += ["", b["a"].upper(), "-" * min(40, len(b["a"]))]
        elif t == "h2":
            out += ["", b["a"]]
        elif t == "p":
            out.append(b["a"])
        elif t == "b":
            out.append("  - " + b["a"])
        elif t == "kv":
            out.append(f"  * {b['a']}: {b['b']}")
        elif t == "qa":
            out += [f"  Q. {b['a']}", f"  A. {b['b']}", ""]
    return "\n".join(out).strip() + "\n"


# ==================================================
# 4. PDF
# ==================================================
def _pdf_reportlab(blocks, title):
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

    reg, bold = "Helvetica", "Helvetica-Bold"
    rp, bp = _find_font("latin"), _find_font("latin_bold")
    if rp:
        try:
            pdfmetrics.registerFont(TTFont("NotesF", rp))
            reg = bold = "NotesF"
            if bp:
                pdfmetrics.registerFont(TTFont("NotesFB", bp))
                bold = "NotesFB"
        except Exception:
            reg, bold = "Helvetica", "Helvetica-Bold"
    brand, ink, mut = colors.HexColor("#3b2fc0"), colors.HexColor("#182033"), colors.HexColor("#667089")
    S = {
        "title": ParagraphStyle("t", fontName=bold, fontSize=21, leading=26, textColor=brand, spaceAfter=2),
        "meta": ParagraphStyle("m", fontName=reg, fontSize=9.5, leading=12, textColor=mut, spaceAfter=6),
        "h": ParagraphStyle("h", fontName=bold, fontSize=14, leading=18, textColor=brand, spaceBefore=12, spaceAfter=3),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=15, textColor=ink, spaceBefore=6, spaceAfter=1),
        "p": ParagraphStyle("p", fontName=reg, fontSize=10.5, leading=15, textColor=ink, spaceAfter=3),
        "b": ParagraphStyle("b", fontName=reg, fontSize=10.5, leading=14.5, textColor=ink, leftIndent=14,
                            bulletIndent=3, spaceAfter=2),
    }
    story = []
    for b in blocks:
        t = b["t"]
        a = escape(b["a"])
        if t in ("title", "meta", "h", "h2", "p"):
            story.append(Paragraph(a, S[t]))
            if t == "h":
                story.append(HRFlowable(width="100%", thickness=.6, color=colors.HexColor("#d9ddf0"), spaceAfter=3))
        elif t == "b":
            story.append(Paragraph(a, S["b"], bulletText="•"))
        elif t == "kv":
            story.append(Paragraph(f"<font name='{bold}'>{a}</font> — {escape(b['b'])}", S["b"], bulletText="•"))
        elif t == "qa":
            story.append(KeepTogether([Paragraph(f"<font name='{bold}'>Q. {a}</font>", S["p"]),
                                       Paragraph(f"A. {escape(b['b'])}", S["b"]), Spacer(1, 3)]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(reg, 8.5)
        canvas.setFillColor(mut)
        canvas.drawString(16 * mm, 9 * mm, "EduVision exam notes")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm,
                      bottomMargin=16 * mm, title=title[:100], author="EduVision").build(
        story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _pdf_pillow(blocks, indic):
    """Kannada / Hindi (and a fallback for English): pages are drawn as pictures so the script is shaped correctly."""
    if indic and not _find_font("indic"):
        raise RuntimeError("No Kannada/Hindi font found. Install 'Nirmala UI' (Windows) or Noto Sans Kannada/Devanagari "
                           "(Linux), or download the notes as text.")
    W, H, M = 1240, 1754, 90
    usable = W - 2 * M
    INK, BRAND, MUT = (24, 32, 51), (59, 47, 192), (102, 112, 139)
    pages, state = [], {}

    def new_page():
        im = Image.new("RGB", (W, H), "white")
        pages.append(im)
        state["d"], state["y"] = ImageDraw.Draw(im), M

    def put(text, size, is_bold, color, indent=0, bullet=False, after=8):
        f = _font(size, is_bold, indic)
        lh = int(size * (1.5 if indic else 1.35))
        lines = _wrap(text, f, usable - indent - (30 if bullet else 0))
        for k, line in enumerate(lines):
            if state["y"] + lh > H - M:
                new_page()
            if bullet and k == 0:
                state["d"].text((M + indent, state["y"]), "•", font=f, fill=color)
            state["d"].text((M + indent + (30 if bullet else 0), state["y"]), line, font=f, fill=color)
            state["y"] += lh
        state["y"] += after

    new_page()
    for b in blocks:
        t = b["t"]
        if t == "title":
            put(b["a"], 46, True, BRAND, after=4)
        elif t == "meta":
            put(b["a"], 24, False, MUT, after=14)
        elif t == "h":
            state["y"] += 14
            put(b["a"], 34, True, BRAND, after=6)
        elif t == "h2":
            put(b["a"], 29, True, INK, after=4)
        elif t == "p":
            put(b["a"], 27, False, INK)
        elif t == "b":
            put(b["a"], 27, False, INK, indent=10, bullet=True, after=5)
        elif t == "kv":
            put(b["a"], 27, True, INK, indent=10, after=1)
            put(b["b"], 27, False, INK, indent=40, after=6)
        elif t == "qa":
            put("Q. " + b["a"], 27, True, INK, indent=10, after=1)
            put("A. " + b["b"], 27, False, INK, indent=40, after=8)
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return buf.getvalue()


def notes_to_pdf(n):
    indic = n.get("language", "English").lower() in SCRIPT_RANGES
    if indic:
        return _pdf_pillow(n["blocks"], True)
    try:
        return _pdf_reportlab(n["blocks"], n["title"])
    except ImportError:
        logger.warning("reportlab is not installed (pip install reportlab); drawing the PDF with Pillow.")
        return _pdf_pillow(n["blocks"], False)


# ==================================================
# 5. ASK A QUESTION ABOUT THE DOCUMENT
# ==================================================
def _pick_context(chunks, question):
    q = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 2 and w not in _STOP}
    scored = []
    for i, ch in enumerate(chunks):
        low = ch.lower()
        scored.append((sum(low.count(w) for w in q) / (len(ch) ** 0.3), i))
    best = [i for sc, i in sorted(scored, reverse=True)[:3] if sc > 0]
    if not best:                                   # e.g. a Kannada question about an English document
        best = list(range(min(len(chunks), 2)))
    return "\n---\n".join(chunks[i] for i in sorted(best))[:12000]


def _answer_algo(chunks, question, language):
    q = {w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in _STOP}
    sents = [s for ch in chunks for s in _sentences(ch)]
    scored = [(sum(1 for w in q if w in s.lower()), -i, s) for i, s in enumerate(sents)]
    best = [s for sc, _, s in sorted(scored, reverse=True)[:3] if sc > 0]
    if not best:
        return {"found": False, "answer": NOT_FOUND.get(language, NOT_FOUND["English"])}
    return {"found": True, "answer": " ".join(best)}


def answer_question(source, question, language="English", history=None):
    question = _ws(question)[:500]
    if not question:
        raise ValueError("Type a question first.")
    language = _pick_language(language)
    chunks = split_chunks(source)
    if ai_available():
        ctx = _pick_context(chunks, question)
        hist = "\n".join(f"Student: {h['q']}\nAnswer: {h['a']}" for h in (history or [])[-3:])
        prompt = f"""
A student asks a question about THEIR OWN document. Answer using ONLY the DOCUMENT EXCERPTS below.
If the answer is not in the excerpts, return found=false and the answer "{NOT_FOUND[language]}".
Do not use outside knowledge. Be clear and brief (at most 120 words), useful for exam revision.
Answer in the same language as the question (English, Kannada or Hindi).
{('Earlier in this chat:' + chr(10) + hist) if hist else ''}

DOCUMENT EXCERPTS:
{ctx}

QUESTION: {question}

Return JSON: {{"found": true, "answer": "..."}}
"""
        try:
            data = ask_json(prompt)
            ans = _ws(data.get("answer"))
            if ans:
                found = data.get("found")
                return {"found": not (found is False or str(found).lower() == "false"), "answer": ans[:1200]}
        except Exception as exc:
            logger.warning("AI answer failed (%s). Using the built-in search.", str(exc)[:120])
    return _answer_algo(chunks, question, language)
