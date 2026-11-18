"""
services/ai_tutor_service.py

AI Doubt-Solving Tutor.

  * Chat answers : Ollama (OLLAMA_URL / OLLAMA_MODEL from .env), Gemini only as a fallback
                   through ai_service.call_model() when Ollama is down.
  * DIAGRAMS     : made by a pure-Python algorithm (the INFOGRAPHIC ENGINE section of this same file).
                   NO Ollama, NO Gemini, NO internet is needed for the picture.
                   The engine returns the content, this file draws it as an SVG infographic
                   (6 panels, always the same style), saves it in static/tutor_diagrams/
                   and attaches it to the answer as a Markdown image.
                   If the chat AI is offline, the diagram is still returned together with a
                   short explanation built from the diagram itself.

This file never imports app.py and creates no database tables.
"""

import copy
import difflib
import html
import json
import logging
import math
import os
import re
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

logger = logging.getLogger(__name__)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM_PROMPT = (
    "You are EduVision AI Tutor, a friendly and intelligent educational assistant.\n\n"
    "Answer students' educational questions across different subjects.\n\n"
    "Explain concepts in simple language, especially for beginners.\n\n"
    "Use real-world examples to make difficult concepts easy to understand.\n\n"
    "For programming questions, provide correct code examples and explain the code step by step.\n\n"
    "For numerical questions, show the solution step by step.\n\n"
    "For exam preparation, provide structured answers with headings and important points.\n\n"
    "Maintain conversation context for follow-up questions.\n\n"
    "If a question is unclear, ask the student for clarification.\n\n"
    "Be accurate, patient, encouraging, and educational.\n\n"
    "Formatting rules: write in Markdown. Use short headings and bullet points where they help. "
    "Put every piece of code inside a fenced code block with the language name. "
    "Reply in the same language the student used."
)

IMAGE_HINT_WITH_IMAGES = (
    "\n\nThe student asked for an image/diagram. A relevant infographic/diagram image is "
    "attached automatically below your answer. Do NOT say you cannot show images "
    "and do NOT write image links yourself. Give a short explanation (5-8 lines) "
    "and briefly walk through the main parts of the diagram."
)

IMAGE_HINT_INFOGRAPHIC = (
    "\n\nThe student asked for a diagram. An infographic is attached automatically below your "
    "answer, followed by a panel-by-panel guide to the picture. Do NOT say you cannot show images "
    "and do NOT write image links yourself. Explain the CONCEPT itself in simple words (6-10 lines), "
    "in the same order as the panels of the infographic, and use an everyday example. "
    "Do not repeat the panel guide; it is added for you."
)

IMAGE_HINT_NO_IMAGES = (
    "\n\nThe student asked for an image/diagram, but no picture could be made. "
    "Do NOT say you cannot show images. Draw a clear, simple diagram using plain "
    "text/ASCII inside a fenced code block (```text), then briefly explain each "
    "labelled part."
)

MAX_QUESTION_CHARS = 2000      # one student question
MAX_MESSAGE_CHARS = 4000       # one remembered message
MAX_HISTORY_MESSAGES = 12      # how many earlier messages the AI remembers
MAX_CONTEXT_CHARS = 7000       # lesson context given to the AI
MAX_IMAGES = 2

IMAGE_MARKER = "\n\n---\n\n### 🖼️ Diagram"   # starts the image block in answers


class TutorError(Exception):
    """An error whose text is safe and helpful to show to the student."""


class _ProviderUnavailable(Exception):
    """Ollama could not be reached (not running, wrong URL, network problem)."""


# ------------------------------------------------------------------ history

def clean_history(history):
    """Keep only valid recent messages: [{'role': 'user'|'assistant', 'content': str}].
    The attached diagram block is removed so it does not use up the AI's memory."""
    cleaned = []
    if not isinstance(history, list):
        return cleaned
    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.split(IMAGE_MARKER)[0].strip()
        if content:
            cleaned.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    return cleaned


# ------------------------------------------------------------- image intent

_IMAGE_WORDS = re.compile(
    r"\b(images?|pictures?|pics?|photos?|diagrams?|illustrations?|infographics?|"
    r"flow ?charts?|sketch(?:es)?|visuals?|figures?(?!\s+out))\b",
    re.IGNORECASE,
)
_DRAW_WORDS = re.compile(r"\b(draw|sketch)\b", re.IGNORECASE)
_CODE_WORDS = re.compile(
    r"\b(code|program|python|java|c\+\+|javascript|function|script|sql|html|css)\b",
    re.IGNORECASE,
)

_FILLER = re.compile(
    r"\b(please|plz|can|could|you|u|me|my|give|show|display|draw|send|provide|"
    r"generate|create|make|want|need|i|a|an|the|of|for|to|about|with|in|on|and|"
    r"it|its|this|that|these|those|image|images|picture|pictures|pic|pics|photo|"
    r"photos|diagram|diagrams|infographic|infographics|figure|figures|illustration|"
    r"illustrations|flowchart|flow chart|sketch|visual|visuals|labelled|labeled|"
    r"related|explain|explanation|how|what|is|are|does|do|work|works|also|again|"
    r"one|more|like|similar|full)\b",
    re.IGNORECASE,
)


def wants_image(question):
    """True if the student is asking for an image / diagram / picture."""
    q = question or ""
    if _IMAGE_WORDS.search(q):
        return True
    return bool(_DRAW_WORDS.search(q)) and not _CODE_WORDS.search(q)


def _topic_from(text):
    text = (text or "").split(IMAGE_MARKER)[0]
    text = _FILLER.sub(" ", text)
    text = re.sub(r"[^\w\s\-+]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def extract_topic(question, history=None, topic_hint=None):
    """'give me a diagram of the human heart' -> 'human heart'.
    If the question has no topic ('show image of it'), use the previous student
    question, then the video title."""
    topic = _topic_from(question)
    if len(topic) < 3:
        for item in reversed(clean_history(history)):
            if item["role"] != "user":
                continue
            earlier = _topic_from(item["content"])
            if len(earlier) >= 3:
                topic = earlier
                break
    if len(topic) < 3 and topic_hint:
        topic = _topic_from(topic_hint) or str(topic_hint).strip()
    return topic[:80]


# ====================================================================
#  INFOGRAPHIC: clean the AI's JSON  ->  draw SVG  ->  save file
# ====================================================================

_PANEL_TYPES = {"chart", "flow", "formula", "steps", "example", "bullets"}


def _s(value, limit):
    """Any value -> short single-line string."""
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return text[:limit]


def _item_text(item, limit=60):
    if isinstance(item, dict):
        item = " - ".join(str(v) for v in item.values() if v)
    elif isinstance(item, (list, tuple)):
        item = " : ".join(str(v) for v in item if v)
    return _s(item, limit)


def _default_panels(title):
    """Template content used for any panel the AI did not produce correctly.
    Keeps the infographic in the same 6-panel style for every topic."""
    title = _s(title, 28) or "Topic"
    return [
        {"type": "flow", "heading": "Key Parts",
         "items": [title, "Main idea", "Result"]},
        {"type": "flow", "heading": "Process",
         "items": ["Input", "Process", "Output"]},
        {"type": "bullets", "heading": "Key Idea",
         "items": [f"Understand {title}", "Learn the basics", "Practice often"]},
        {"type": "steps", "heading": "How It Works?",
         "items": ["Learn the basic idea.", "Apply it to a problem.", "Check your result."]},
        {"type": "example", "heading": "Example",
         "intro": f"Think of {title}", "calc": "", "result": "in everyday life."},
        {"type": "bullets", "heading": "Applications",
         "items": ["Education", "Industry", "Research", "Daily life"]},
    ]


def _clean_panel(p):
    """Validate ONE panel. Returns a safe panel dict, or None if nothing can be drawn."""
    if not isinstance(p, dict):
        return None
    ptype = _s(p.get("type"), 12).lower()
    if ptype not in _PANEL_TYPES:
        ptype = "bullets"
    heading = _s(p.get("heading") or p.get("title"), 28)
    raw_items = p.get("items") if isinstance(p.get("items"), list) else []
    panel = {"type": ptype, "heading": heading}

    if ptype == "chart":
        points = []
        raw_points = p.get("points")
        for pt in raw_points if isinstance(raw_points, list) else []:
            if isinstance(pt, dict):
                pt = [pt.get("x"), pt.get("y")]
            try:
                points.append((float(pt[0]), float(pt[1])))
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        if len(points) < 3:
            ptype = "flow" if raw_items else "bullets"
            panel["type"] = ptype
        else:
            panel.update(points=points[:14],
                         x_label=_s(p.get("x_label"), 30),
                         y_label=_s(p.get("y_label"), 24),
                         line=bool(p.get("line")),
                         line_label=_s(p.get("line_label") or "Best-fit line", 22))

    if ptype == "formula":
        formula = _s(p.get("formula"), 40)
        legend = []
        for it in raw_items[:5]:
            if isinstance(it, dict):
                sym = it.get("symbol") or it.get("term") or ""
                mean = it.get("meaning") or it.get("description") or ""
            elif isinstance(it, (list, tuple)) and len(it) >= 2:
                sym, mean = it[0], it[1]
            else:
                sym, _, mean = str(it).partition(":")
            sym, mean = _s(sym, 8), _s(mean, 34)
            if sym and mean:
                legend.append((sym, mean))
        if formula:
            panel.update(formula=formula, legend=legend)
        else:
            panel["type"] = ptype = "bullets"
            raw_items = [f"{a}: {b}" for a, b in legend]

    if ptype == "example":
        panel.update(intro=_s(p.get("intro"), 50),
                     calc=_s(p.get("calc"), 46),
                     result=_s(p.get("result"), 70))

    if panel["type"] in ("flow", "steps", "bullets"):
        panel["items"] = [t for t in (_item_text(i, 60) for i in raw_items[:6]) if t]

    t = panel["type"]
    ok = (
        (t == "chart" and panel.get("points"))
        or (t == "formula" and panel.get("formula"))
        or (t == "example" and (panel.get("calc") or panel.get("intro")))
        or (t in ("flow", "steps", "bullets") and panel.get("items"))
    )
    return panel if ok else None


def _clean_spec(raw):
    """Validate and shorten the AI's JSON. Returns a safe dict with EXACTLY 6 panels
    (bad/missing panels are filled from the template), or None if the AI's answer
    is unusable (fewer than 3 good panels or no title)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("panels"), list):
        return None
    title = _s(raw.get("title"), 34)
    if not title:
        return None

    panels = [_clean_panel(p) for p in raw["panels"][:6]]   # None keeps the slot position
    while len(panels) < 6:
        panels.append(None)
    if sum(1 for p in panels if p) < 3:
        return None

    defaults = _default_panels(title)
    panels = [p or defaults[i] for i, p in enumerate(panels)]
    return {"title": title, "subtitle": _s(raw.get("subtitle"), 90), "panels": panels}


# ---------------------------------------------------------- SVG primitives

_SANS = "Segoe UI, Helvetica, Arial, sans-serif"
_SERIF = "Cambria Math, Cambria, Georgia, 'Times New Roman', serif"

_PALETTES = [   # (header fill, border colour) for the six panels
    ("#b8dcff", "#3d8be0"),
    ("#bfeaa3", "#4fb05a"),
    ("#cfc2ef", "#8c72d4"),
    ("#fdd67f", "#f0a528"),
    ("#a9e4b4", "#35ad57"),
    ("#f8a9b6", "#e2506a"),
]
_SLOTS = [      # x, y, width, height of the six panels (1536 x 1024 canvas)
    (14, 198, 503, 476), (587, 198, 491, 476), (1133, 198, 388, 476),
    (14, 712, 540, 286), (577, 712, 515, 286), (1115, 712, 407, 286),
]
_HEADER_H = 66
_INK = "#1b2a41"


def _text(x, y, text, size, fill=_INK, weight="400", anchor="start", family=_SANS, style="normal"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}" font-family="{family}" font-style="{style}">'
        f"{html.escape(str(text), quote=True)}</text>"
    )


def _rect(x, y, w, h, fill="none", stroke="none", sw=0, rx=0):
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    )


def _wrap(text, size, max_width):
    chars = max(6, int(max_width / (size * 0.53)))
    return textwrap.wrap(str(text), chars) or [""]


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _nice_step(span, ticks=4):
    raw = span / ticks if span > 0 else 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


# ----------------------------------------------------------- panel bodies

def _num_marker(n, cx, cy, acc):
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="18" fill="#f59e0b"/>'
        + _text(cx, cy + 8, n, 22, "#ffffff", "700", "middle")
    )


def _check_marker(n, cx, cy, acc):
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="17" fill="#22a355"/>'
        f'<path d="M{cx - 8:.1f} {cy:.1f} L{cx - 2:.1f} {cy + 7:.1f} L{cx + 9:.1f} {cy - 7:.1f}" '
        f'fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _list_block(items, x, y, w, h, marker, acc):
    """Numbered / checked list; text shrinks until everything fits the box."""
    size = 30
    while True:
        wrapped = [_wrap(i, size, w - 56) for i in items]
        lh, gap = size * 1.22, size * 0.6
        total = sum(len(lines) * lh for lines in wrapped) + gap * (len(items) - 1)
        if total <= h or size <= 16:
            break
        size -= 2
    cy = y + max(0, (h - total) / 2)
    out = []
    for n, lines in enumerate(wrapped, 1):
        block = len(lines) * lh
        out.append(marker(n, x + 19, cy + block / 2, acc))
        for k, line in enumerate(lines):
            out.append(_text(x + 52, cy + lh * k + size * 0.9, line, size))
        cy += block + gap
    return out


def _chart(p, x, y, w, h, acc):
    pts = p["points"]
    xs, ys = [a for a, _ in pts], [b for _, b in pts]
    xmin, ymin = min(0, min(xs)), min(0, min(ys))
    xstep, ystep = _nice_step(max(xs) - xmin), _nice_step(max(ys) - ymin)
    xmax = xmin + xstep * math.ceil((max(xs) - xmin) / xstep + 0.2)
    ymax = ymin + ystep * math.ceil((max(ys) - ymin) / ystep + 0.2)

    left, right = x + 78, x + w - 12
    top, bottom = y + 10, y + h - 74

    def sx(v):
        return left + (v - xmin) / (xmax - xmin) * (right - left)

    def sy(v):
        return bottom - (v - ymin) / (ymax - ymin) * (bottom - top)

    out = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#222" stroke-width="2.5"/>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#222" stroke-width="2.5"/>',
    ]
    for i in range(int(round((xmax - xmin) / xstep)) + 1):
        v = xmin + i * xstep
        out.append(f'<line x1="{sx(v):.1f}" y1="{bottom}" x2="{sx(v):.1f}" y2="{bottom + 8}" stroke="#222" stroke-width="2"/>')
        out.append(_text(sx(v), bottom + 36, _fmt(v), 26, anchor="middle"))
    for i in range(int(round((ymax - ymin) / ystep)) + 1):
        v = ymin + i * ystep
        out.append(f'<line x1="{left - 8}" y1="{sy(v):.1f}" x2="{left}" y2="{sy(v):.1f}" stroke="#222" stroke-width="2"/>')
        out.append(_text(left - 14, sy(v) + 9, _fmt(v), 26, anchor="end"))

    if p.get("line") and len(pts) >= 2:                       # least-squares line
        n = len(pts)
        mx, my = sum(xs) / n, sum(ys) / n
        var = sum((a - mx) ** 2 for a in xs)
        if var > 0:
            slope = sum((a - mx) * (b - my) for a, b in pts) / var
            icpt = my - slope * mx
            x1 = max(xmin, min(xs) - 0.3 * xstep)
            x2 = min(xmax, max(xs) + 0.3 * xstep)
            out.append(
                f'<line x1="{sx(x1):.1f}" y1="{sy(slope * x1 + icpt):.1f}" '
                f'x2="{sx(x2):.1f}" y2="{sy(slope * x2 + icpt):.1f}" '
                f'stroke="#e5252a" stroke-width="6" stroke-linecap="round"/>'
            )
    for a, b in pts:
        out.append(f'<circle cx="{sx(a):.1f}" cy="{sy(b):.1f}" r="8" fill="#1f6fdc"/>')

    if p.get("line"):                                          # legend box
        lw = min(w - 100, 60 + len(p["line_label"]) * 14)
        lx = right - lw
        out.append(_rect(lx, top - 2, lw, 46, "#ffffff", "#9aa3b2", 2, 8))
        out.append(f'<line x1="{lx + 12}" y1="{top + 21}" x2="{lx + 52}" y2="{top + 21}" stroke="#e5252a" stroke-width="6" stroke-linecap="round"/>')
        out.append(_text(lx + 62, top + 31, p["line_label"], 24))

    if p.get("x_label"):
        out.append(_text((left + right) / 2, y + h - 12, p["x_label"], 24, anchor="middle"))
    if p.get("y_label"):
        yy = (top + bottom) / 2
        out.append(
            f'<g transform="rotate(-90 {x + 16:.1f} {yy:.1f})">'
            + _text(x + 16, yy + 8, p["y_label"], 22, anchor="middle") + "</g>"
        )
    return out


def _flow(p, x, y, w, h, acc):
    items = p["items"][:6]
    n = len(items)
    arrow = 26 if n > 1 else 0
    box_h = min(78.0, (h - arrow * (n - 1)) / n)
    size = 26
    while size > 15 and any(len(_wrap(i, size, w - 36)) * size * 1.2 > box_h - 12 for i in items):
        size -= 2
    total = n * box_h + arrow * (n - 1)
    cy = y + max(0, (h - total) / 2)
    tints = ["#e8f3ff", "#eaf8e0", "#f1ecfc", "#fff3d6", "#e3f7e8", "#fde8ec"]
    out = []
    for k, label in enumerate(items):
        out.append(_rect(x, cy, w, box_h, tints[k % 6], acc, 2.5, 14))
        lines = _wrap(label, size, w - 36)
        ty = cy + box_h / 2 - (len(lines) - 1) * size * 0.6 + size * 0.33
        for j, line in enumerate(lines):
            out.append(_text(x + w / 2, ty + j * size * 1.2, line, size, weight="600", anchor="middle"))
        cy += box_h
        if k < n - 1:
            mid = x + w / 2
            out.append(f'<polygon points="{mid - 12},{cy + 3} {mid + 12},{cy + 3} {mid},{cy + arrow - 3}" fill="{acc}"/>')
            cy += arrow
    return out


def _formula(p, x, y, w, h, acc):
    box_h = min(118.0, h * 0.34)
    out = [_rect(x, y, w, box_h, "#e5e0f7", "none", 0, 14)]
    f = p["formula"]
    size = max(16, min(58, int((w - 30) / (len(f) * 0.55))))
    out.append(_text(x + w / 2, y + box_h / 2 + size * 0.32, f, size, anchor="middle",
                     family=_SERIF, style="italic"))
    legend = p.get("legend") or []
    if legend:
        top = y + box_h + 18
        row = min(56.0, (h - box_h - 18) / len(legend))
        for k, (sym, mean) in enumerate(legend):
            cy = top + row * k + row * 0.68
            msize = max(16, min(30, (w - 96) / (len(mean) * 0.53)))
            ssize = max(16, min(34, int(120 / max(len(sym), 1))))     # long symbols get smaller text
            out.append(_text(x + 28, cy, sym, ssize, anchor="middle", family=_SERIF, style="italic"))
            out.append(_text(x + 64, cy, ":", 30))
            out.append(_text(x + 88, cy, mean, msize))
    return out


def _example(p, x, y, w, h, acc):
    size = 30
    while True:                                   # shrink the text until everything fits the panel
        lh = size * 1.2
        intro = _wrap(p["intro"], size, w) if p.get("intro") else []
        result = _wrap(p["result"], size, w) if p.get("result") else []
        box_h = (size * 2.2) if p.get("calc") else 0
        gap = 12
        total = (len(intro) * lh + (gap + box_h if box_h else 0)
                 + (gap + len(result) * lh if result else 0))
        if total <= h or size <= 16:
            break
        size -= 2
    cy = y + max(0, (h - total) / 2)
    out = []
    for line in intro:
        out.append(_text(x + w / 2, cy + size * 0.9, line, size, anchor="middle"))
        cy += lh
    if box_h:
        cy += gap
        out.append(_rect(x + 6, cy, w - 12, box_h, "#d6f2d0", "none", 0, 12))
        csize = max(16, min(40, int((w - 40) / (len(p["calc"]) * 0.55))))
        out.append(_text(x + w / 2, cy + box_h / 2 + csize * 0.33, p["calc"], csize,
                         anchor="middle", family=_SERIF))
        cy += box_h
    if result:
        cy += gap
        for line in result:
            out.append(_text(x + w / 2, cy + size * 0.9, line, size, anchor="middle"))
            cy += lh
    return out


def _render_panel(slot, palette, p):
    x, y, w, h = slot
    head, border = palette
    heading = p["heading"] or ""
    hsize = max(22, min(40, (w - 30) / (max(len(heading), 1) * 0.56)))
    out = [
        _rect(x, y, w, h, "#ffffff", border, 3, 18),
        f'<path d="M{x},{y + _HEADER_H} V{y + 18} Q{x},{y} {x + 18},{y} H{x + w - 18} '
        f'Q{x + w},{y} {x + w},{y + 18} V{y + _HEADER_H} Z" fill="{head}"/>',
        f'<line x1="{x}" y1="{y + _HEADER_H}" x2="{x + w}" y2="{y + _HEADER_H}" stroke="{border}" stroke-width="3"/>',
        _rect(x, y, w, h, "none", border, 3, 18),
        _text(x + w / 2, y + _HEADER_H / 2 + hsize * 0.35, heading, hsize, weight="700", anchor="middle"),
    ]
    bx, by = x + 22, y + _HEADER_H + 16
    bw, bh = w - 44, h - _HEADER_H - 32
    t = p["type"]
    if t == "chart":
        out += _chart(p, bx, by, bw, bh, border)
    elif t == "flow":
        out += _flow(p, bx, by, bw, bh, border)
    elif t == "formula":
        out += _formula(p, bx, by, bw, bh, border)
    elif t == "example":
        out += _example(p, bx, by, bw, bh, border)
    elif t == "steps":
        out += _list_block(p["items"], bx, by, bw, bh, _num_marker, border)
    else:
        out += _list_block(p["items"], bx, by, bw, bh, _check_marker, border)
    return out


def render_infographic_svg(spec):
    """spec (from _clean_spec) -> complete SVG text, 1536 x 1024."""
    W, H = 1536, 1024
    title, subtitle = spec["title"], spec["subtitle"]
    tsize = max(34, min(60, int(900 / (len(title) * 0.56))))
    bw = min(1200, len(title) * tsize * 0.58 + 120)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        _rect((W - bw) / 2, 14, bw, 92, "#1d3f75", "none", 0, 24),
        _text(W / 2, 14 + 46 + tsize * 0.35, title, tsize, "#ffffff", "700", "middle"),
    ]
    if subtitle:
        ssize = max(22, min(38, int(1440 / (len(subtitle) * 0.52))))
        parts.append(_text(W / 2, 152, subtitle, ssize, "#1d3a6e", "500", "middle"))

    for slot, palette, panel in zip(_SLOTS, _PALETTES, spec["panels"]):
        parts += _render_panel(slot, palette, panel)

    if len(spec["panels"]) >= 2:    # arrow between panel 1 and 2
        parts.append('<polygon points="524,432 550,432 550,414 582,445 550,476 550,458 524,458" fill="#1d3f75"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _diagram_folder():
    return os.getenv("TUTOR_DIAGRAM_DIR") or os.path.join(PROJECT_ROOT, "static", "tutor_diagrams")


def _cleanup_old(folder, days=7):
    cutoff = time.time() - days * 86400
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name.endswith(".svg") and os.path.getmtime(path) < cutoff:
                os.remove(path)
    except OSError:
        pass


def save_infographic(svg, topic):
    """Write the SVG into static/tutor_diagrams/ and return its URL."""
    folder = _diagram_folder()
    os.makedirs(folder, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (topic or "").lower()).strip("-")[:40] or "diagram"
    name = f"{slug}-{uuid.uuid4().hex[:8]}.svg"
    with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
        handle.write(svg)
    _cleanup_old(folder)
    # Diagrams are served by the blueprint route /ai-tutor/diagram/<file> (routes/ai_tutor.py),
    # so they show up even if the Flask static folder is set up differently.
    base = os.getenv("TUTOR_DIAGRAM_URL", "/ai-tutor/diagram").rstrip("/")
    return f"{base}/{name}"



# ====================================================================
#  INFOGRAPHIC ENGINE (pure Python, NO AI model)
#  build_infographic_spec(topic, question, topic_hint) -> content dict
#  1. TOPIC LIBRARY (32 topics, fuzzy matching)  2. optional Wikipedia text
#  3. category templates for every other topic.
#  Add your own topic with one  _K([...aliases...], title, subtitle, ...)  block.
# ====================================================================


# ------------------------------------------------------------ panel builders

def _pflow(heading, items):
    return {"type": "flow", "heading": heading, "items": list(items)}


def _pbul(heading, items):
    return {"type": "bullets", "heading": heading, "items": list(items)}


def _psteps(items, heading="How It Works?"):
    return {"type": "steps", "heading": heading, "items": list(items)}


def _pformula(heading, formula, legend):
    return {"type": "formula", "heading": heading, "formula": formula,
            "items": [list(x) for x in legend]}


def _pex(intro, calc, result, heading="Example"):
    return {"type": "example", "heading": heading, "intro": intro,
            "calc": calc, "result": result}


def _pchart(heading, xl, yl, pts, line=False, line_label=""):
    return {"type": "chart", "heading": heading, "x_label": xl, "y_label": yl,
            "points": [list(p) for p in pts], "line": line, "line_label": line_label}


# ------------------------------------------------------------ topic library

_KB = []


def _K(aliases, title, subtitle, p1, p2, p3, steps, example, apps):
    _KB.append({
        "aliases": aliases, "title": title, "subtitle": subtitle,
        "panels": [p1, p2, p3, _psteps(steps), example, _pbul("Applications", apps)],
    })


_LR = [(1, 20), (2, 32), (3, 48), (3.5, 39), (4.3, 53), (5.3, 58), (5.4, 44),
       (5.9, 69), (7, 61), (7.2, 75)]
_SIG = [(x, round(1 / (1 + math.exp(-x)), 3)) for x in range(-4, 5)]
_OHM = [(i, 2 * i) for i in range(1, 7)]
_QUAD = [(x, x * x - 5 * x + 6) for x in range(0, 7)]

_K(["linear regression", "regression", "line of best fit", "best fit line", "least squares"],
   "Linear Regression", "Finds the best-fit straight line to predict a continuous value.",
   _pchart("Data Points", "X (Independent Variable)", "Y (Dependent)", _LR),
   _pchart("Best-Fit Line", "X (Independent Variable)", "Y (Dependent)", _LR, True, "Regression Line"),
   _pformula("Regression Equation", "ŷ = β₀ + β₁x",
            [("ŷ", "Predicted value"), ("β₀", "Intercept"), ("β₁", "Slope")]),
   ["Find the line that minimizes the error (least squares).",
    "Use the line to make predictions.", "Measure accuracy (e.g., R², MSE)."],
   _pex("If x = 6,", "ŷ = 5 + 7(6) = 47", "So, the predicted value is 47.", "Example Prediction"),
   ["Sales Forecasting", "House Price Prediction", "Trend Analysis", "Medical Research"])

_K(["logistic regression", "sigmoid function", "sigmoid"],
   "Logistic Regression", "Predicts the probability that an input belongs to a class.",
   _pflow("Model Flow", ["Input features (x)", "Weighted sum z = wx + b", "Sigmoid function",
                        "Probability (0 to 1)", "Class label (0 or 1)"]),
   _pchart("Sigmoid Curve", "z (weighted sum)", "Probability p", _SIG),
   _pformula("Sigmoid Formula", "p = 1 / (1 + e⁻ᶻ)",
            [("p", "Probability"), ("z", "wx + b"), ("e", "Euler's number")]),
   ["Compute z = wx + b.", "Apply sigmoid to get a probability.", "If p ≥ 0.5, predict class 1."],
   _pex("If z = 0,", "p = 1 / (1 + 1) = 0.5", "So, the probability is 50%."),
   ["Spam Detection", "Disease Diagnosis", "Credit Risk", "Customer Churn"])

_K(["neural network", "artificial neural network", "ann", "deep learning", "perceptron"],
   "Neural Network", "Layers of connected neurons that learn patterns from data.",
   _pflow("Network Layers", ["Input layer", "Hidden layer(s)", "Output layer"]),
   _pflow("Forward Pass", ["Receive inputs", "Weighted sum + bias", "Activation function",
                          "Pass to next layer", "Output prediction"]),
   _pformula("Neuron Output", "a = f(Σwᵢxᵢ + b)",
            [("w", "Weight"), ("b", "Bias"), ("f", "Activation function")]),
   ["Forward pass: compute predictions.", "Compute the loss (error).",
    "Backpropagate and update weights."],
   _pex("If x = 2, w = 3, b = 1,", "z = 3(2) + 1 = 7", "So, ReLU(7) = 7 goes forward."),
   ["Image Recognition", "Speech Assistants", "Language Translation", "Self-Driving Cars"])

_K(["decision tree"],
   "Decision Tree", "Splits data with yes/no questions until it can give an answer.",
   _pflow("Tree Parts", ["Root node", "Decision nodes", "Branches", "Leaf nodes (answers)"]),
   _pflow("Building the Tree", ["Pick the best feature", "Split the data", "Repeat on each branch",
                               "Stop at a pure leaf", "Predict the class"]),
   _pformula("Gini Impurity", "Gini = 1 − Σpᵢ²",
            [("Gini", "Impurity of a node"), ("pᵢ", "Share of class i")]),
   ["Choose the split with lowest impurity.", "Grow branches until nodes are pure.",
    "Prune the tree to avoid overfitting."],
   _pex("Node with 50% / 50% classes,", "Gini = 1 − (0.25 + 0.25) = 0.5", "So, the node is fully mixed."),
   ["Loan Approval", "Medical Diagnosis", "Customer Segments", "Fraud Detection"])

_K(["k-means", "k means clustering", "clustering"],
   "K-Means Clustering", "Groups similar data points into K clusters.",
   _pflow("Key Ideas", ["Unlabelled data points", "K cluster centres", "Nearest-centre rule"]),
   _pflow("Algorithm Loop", ["Choose K", "Place K centroids", "Assign points to nearest",
                            "Move centroids to the mean", "Repeat until stable"]),
   _pformula("Distance", "d = √((x₂−x₁)² + (y₂−y₁)²)",
            [("d", "Distance"), ("(x, y)", "Point coordinates")]),
   ["Assign every point to its nearest centroid.", "Recompute each centroid as cluster mean.",
    "Stop when assignments stop changing."],
   _pex("Point (1, 2), centroid (4, 6):", "d = √(9 + 16) = 5", "So, the distance is 5."),
   ["Customer Segmentation", "Image Compression", "Document Grouping", "Anomaly Detection"])

_K(["machine learning", "ml", "artificial intelligence", "ai"],
   "Machine Learning", "Computers learn patterns from data instead of fixed rules.",
   _pflow("Core Parts", ["Data", "Features", "Model", "Prediction"]),
   _pflow("ML Pipeline", ["Collect data", "Clean the data", "Train the model",
                         "Test the model", "Deploy and monitor"]),
   _pbul("Types of ML", ["Supervised learning", "Unsupervised learning",
                        "Reinforcement learning", "Semi-supervised learning"]),
   ["Feed data to an algorithm.", "The model learns patterns from it.", "Use the model to predict new data."],
   _pex("Emails labelled spam or not,", "Model learns the patterns", "Then it flags new spam emails."),
   ["Recommendation Systems", "Fraud Detection", "Voice Assistants", "Medical Imaging"])

_K(["photosynthesis"],
   "Photosynthesis", "Plants turn sunlight, water and CO₂ into food and oxygen.",
   _pflow("Inputs", ["Sunlight", "Water (H₂O)", "Carbon dioxide (CO₂)", "Chlorophyll"]),
   _pflow("Process", ["Light absorbed by leaf", "Water split into H and O",
                     "CO₂ converted to sugar", "Oxygen released"]),
   _pformula("Equation", "6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂",
            [("CO₂", "Carbon dioxide"), ("H₂O", "Water"), ("C₆H₁₂O₆", "Glucose")]),
   ["Leaves absorb sunlight.", "Roots supply water.", "Glucose and oxygen are made."],
   _pex("In a sunny garden,", "Light + CO₂ + H₂O → Sugar", "The plant grows and releases O₂."),
   ["Food Production", "Oxygen Supply", "Biofuels", "Climate Research"])

_K(["heart", "human heart", "cardiac", "circulatory system", "blood circulation"],
   "The Human Heart", "A muscular pump that sends blood around the body.",
   _pflow("Heart Chambers", ["Right atrium", "Right ventricle", "Left atrium", "Left ventricle"]),
   _pflow("Blood Flow", ["Body → right atrium", "Right ventricle → lungs", "Lungs add oxygen",
                        "Left atrium → left ventricle", "Left ventricle → body"]),
   _pbul("Key Facts", ["4 chambers and 4 valves", "About 72 beats per minute",
                      "Pumps about 5 litres per minute", "About the size of a fist"]),
   ["Right side sends blood to the lungs.", "Left side sends blood to the body.",
    "Valves keep blood flowing one way."],
   _pex("At rest: 72 beats, 70 mL each,", "72 × 70 ≈ 5040 mL per min", "So, about 5 litres per minute."),
   ["Cardiology", "ECG Monitoring", "Heart Surgery", "Fitness Tracking"])

_K(["water cycle", "hydrological cycle", "rain cycle"],
   "Water Cycle", "Water moves between oceans, air and land again and again.",
   _pflow("Key Players", ["Sun (heat energy)", "Oceans, lakes, rivers",
                         "Clouds in the atmosphere", "Land and groundwater"]),
   _pflow("The Cycle", ["Evaporation", "Condensation", "Precipitation",
                       "Runoff and infiltration", "Collection"]),
   _pbul("Key Facts", ["The sun powers the cycle", "Water is reused again and again",
                      "About 97% of water is in oceans"]),
   ["Heat turns water into vapour.", "Vapour cools into clouds.", "Rain or snow returns water to Earth."],
   _pex("Sun heats a lake,", "Water → Vapour → Cloud → Rain", "So, the water returns to Earth."),
   ["Weather Forecasting", "Agriculture", "Water Supply", "Flood Control"])

_K(["digestive system", "digestion", "human digestive system"],
   "Digestive System", "Breaks food into nutrients the body can absorb.",
   _pflow("Organs", ["Mouth", "Oesophagus", "Stomach", "Small intestine", "Large intestine"]),
   _pflow("Food Journey", ["Ingestion", "Digestion", "Absorption", "Assimilation", "Egestion"]),
   _pbul("Key Facts", ["Digestion starts in the mouth", "Stomach acid breaks down food",
                      "Most absorption: small intestine", "Large intestine absorbs water"]),
   ["Food is chewed and mixed with saliva.", "Enzymes break food into nutrients.",
    "Blood carries nutrients to the body."],
   _pex("A piece of bread,", "Starch → Sugar (glucose)", "So, the body gets energy."),
   ["Nutrition Planning", "Gastro Medicine", "Diet Science", "Food Technology"])

_K(["cell", "animal cell", "plant cell", "cell structure"],
   "The Cell", "The basic building block of all living things.",
   _pflow("Cell Parts", ["Cell membrane", "Nucleus", "Cytoplasm", "Mitochondria", "Ribosomes"]),
   _pflow("Cell Functions", ["Take in nutrients", "Make energy (ATP)", "Make proteins",
                            "Remove waste", "Divide to multiply"]),
   _pbul("Types of Cells", ["Prokaryotic: no nucleus", "Eukaryotic: has a nucleus",
                           "Plant cells have a cell wall", "Animal cells have no cell wall"]),
   ["The membrane controls what enters.", "The nucleus holds the DNA.", "Mitochondria release energy."],
   _pex("A muscle cell needs energy,", "Glucose + O₂ → ATP", "So, the cell can contract."),
   ["Medicine", "Genetics", "Biotechnology", "Cancer Research"])

_K(["dna", "gene", "genetics", "genetic material"],
   "DNA", "The molecule that stores the instructions of life.",
   _pflow("DNA Structure", ["Sugar-phosphate backbone", "Nitrogen bases", "Double helix", "Genes"]),
   _pflow("DNA to Protein", ["DNA", "Transcription", "mRNA", "Translation", "Protein"]),
   _pbul("Base Pairing", ["Adenine (A) pairs with Thymine (T)", "Guanine (G) pairs with Cytosine (C)",
                         "Two strands form a double helix"]),
   ["The helix unzips into two strands.", "Each strand is copied by pairing bases.",
    "Two identical DNA molecules form."],
   _pex("Strand: A T G C,", "Pair: T A C G", "So, the partner strand is TACG."),
   ["Forensic Science", "Genetic Testing", "Gene Therapy", "Crop Improvement"])

_K(["newton law of motion", "law of motion", "newton law", "newton"],
   "Newton's Laws of Motion", "Three laws that explain how forces change motion.",
   _pflow("Three Laws", ["1st: Law of inertia", "2nd: F = m × a", "3rd: Action and reaction"]),
   _pflow("Motion Chain", ["Apply a force", "Mass resists the change", "Acceleration happens",
                          "Reaction force pushes back"]),
   _pformula("Second Law", "F = m × a",
            [("F", "Force (newtons)"), ("m", "Mass (kg)"), ("a", "Acceleration (m/s²)")]),
   ["No force: motion stays unchanged.", "More force gives more acceleration.", "Forces always come in pairs."],
   _pex("If m = 5 kg and a = 3 m/s²,", "F = 5 × 3 = 15 N", "So, the force is 15 newtons."),
   ["Vehicle Safety", "Rocket Launches", "Sports Science", "Machine Design"])

_K(["ohm law", "electric circuit", "electricity", "current electricity"],
   "Ohm's Law", "Voltage, current and resistance are linked by a simple rule.",
   _pflow("Circuit Parts", ["Battery (voltage V)", "Wire (current I)", "Resistor (R)"]),
   _pchart("V–I Graph", "Current I (A)", "Voltage V (V)", _OHM, True, "Slope = R"),
   _pformula("Ohm's Law", "V = I × R",
            [("V", "Voltage (volts)"), ("I", "Current (amperes)"), ("R", "Resistance (ohms)")]),
   ["Voltage pushes the current.", "Resistance opposes the current.", "V grows in proportion to I."],
   _pex("If I = 2 A and R = 5 Ω,", "V = 2 × 5 = 10 V", "So, the voltage is 10 volts."),
   ["Home Wiring", "Electronics Design", "Heaters", "Battery Systems"])

_K(["pythagoras theorem", "pythagorean theorem", "pythagoras", "right triangle", "right angled triangle"],
   "Pythagoras Theorem", "In a right triangle, the squares of the legs add up to c².",
   _pflow("Right Triangle", ["Right angle (90°)", "Two legs: a and b", "Hypotenuse: c"]),
   _pflow("Using the Theorem", ["Find the right angle", "Square both legs",
                               "Add the two squares", "Take the square root"]),
   _pformula("Theorem", "a² + b² = c²",
            [("a, b", "The two legs"), ("c", "Hypotenuse (longest side)")]),
   ["Square the length of each leg.", "Add the two squares together.", "Square root gives the hypotenuse."],
   _pex("If a = 3 and b = 4,", "c = √(9 + 16) = 5", "So, the hypotenuse is 5."),
   ["Construction", "Navigation", "Architecture", "Computer Graphics"])

_K(["quadratic equation", "quadratic formula", "quadratic", "parabola"],
   "Quadratic Equation", "An equation of the form ax² + bx + c = 0 with two roots.",
   _pchart("Parabola Graph", "x", "y = x² − 5x + 6", _QUAD),
   _pflow("Solving Steps", ["Write ax² + bx + c = 0", "Find a, b and c", "Compute D = b² − 4ac",
                           "Apply the formula", "Get the two roots"]),
   _pformula("Quadratic Formula", "x = (−b ± √(b² − 4ac)) / 2a",
            [("a, b, c", "Coefficients"), ("D", "Discriminant"), ("x", "Roots")]),
   ["D > 0: two real roots.", "D = 0: one repeated root.", "D < 0: no real roots."],
   _pex("For x² − 5x + 6 = 0,", "x = (5 ± 1) / 2 = 3 or 2", "So, the roots are 2 and 3."),
   ["Projectile Motion", "Business Profit", "Bridge Design", "Computer Graphics"])

_K(["probability", "chance", "likelihood"],
   "Probability", "Measures how likely an event is to happen.",
   _pflow("Key Terms", ["Experiment", "Sample space (all outcomes)", "Event (wanted outcomes)"]),
   _pflow("Finding Probability", ["Define the experiment", "List all outcomes",
                                 "Count favourable outcomes", "Divide favourable by total"]),
   _pformula("Probability Formula", "P(E) = n(E) / n(S)",
            [("P(E)", "Probability of event"), ("n(E)", "Favourable outcomes"), ("n(S)", "Total outcomes")]),
   ["Probability is always between 0 and 1.", "0 means impossible, 1 means certain.",
    "All probabilities add up to 1."],
   _pex("Rolling a die, P(even):", "P = 3 / 6 = 0.5", "So, the chance is 50%."),
   ["Weather Forecasts", "Insurance", "Games and Gambling", "Machine Learning"])

_K(["mean median mode", "mean", "median", "mode", "average", "central tendency"],
   "Mean, Median and Mode", "Three ways to describe the centre of a data set.",
   _pflow("Three Averages", ["Mean: the average", "Median: the middle value", "Mode: most frequent value"]),
   _pflow("Finding Them", ["Collect the data", "Sort the values", "Add all, divide by n",
                          "Pick the middle value", "Count the repeats"]),
   _pformula("Mean Formula", "Mean = Σx / n", [("Σx", "Sum of all values"), ("n", "Number of values")]),
   ["Mean uses every value.", "Median ignores extreme values.", "Mode shows the most common value."],
   _pex("Data: 2, 4, 4, 6, 9", "Mean = 25 / 5 = 5", "So, median = 4 and mode = 4."),
   ["Exam Results", "Business Reports", "Weather Data", "Sports Statistics"])

_K(["binary search", "binary search algorithm"],
   "Binary Search", "Finds a value in a sorted list by halving the search range.",
   _pflow("Key Parts", ["Sorted array", "Low and high pointers", "Mid index", "Target value"]),
   _pflow("Search Steps", ["Set low = 0, high = n − 1", "Find mid = (low + high) / 2",
                          "Compare target with mid", "Discard the wrong half", "Repeat until found"]),
   _pformula("Middle Index", "mid = (low + high) / 2",
            [("low", "Start index"), ("high", "End index"), ("mid", "Middle index")]),
   ["Array must be sorted first.", "Each step halves the search range.", "Time complexity is O(log n)."],
   _pex("Find 7 in [1, 3, 5, 7, 9],", "mid = 2 (5) → mid = 3 (7)", "So, 7 is found at index 3."),
   ["Dictionary Lookup", "Database Indexing", "Debugging (git bisect)", "Number Guessing Games"])

_K(["bubble sort", "sorting", "sorting algorithm", "sort"],
   "Bubble Sort", "Repeatedly swaps neighbouring values that are in the wrong order.",
   _pflow("Key Parts", ["Array of values", "Adjacent pairs", "Passes (rounds)"]),
   _pflow("Sorting Steps", ["Compare adjacent items", "Swap if out of order", "Largest moves to the end",
                           "Repeat for every pass", "Stop when sorted"]),
   _pbul("Complexity", ["Worst case: O(n²)", "Best case: O(n) with early stop",
                       "Extra space: O(1)", "Stable sorting algorithm"]),
   ["Compare two neighbouring values.", "Swap them if the left is larger.",
    "Repeat until no swaps are needed."],
   _pex("Sort [5, 2, 8, 1],", "Pass 1 → [2, 5, 1, 8]", "Final result: [1, 2, 5, 8]."),
   ["Teaching Algorithms", "Small Data Sets", "Nearly Sorted Data", "Algorithm Practice"])

_K(["stack", "stack data structure"],
   "Stack", "A last-in, first-out collection of items.",
   _pflow("Stack Parts", ["Top (push / pop here)", "Elements", "Bottom"]),
   _pflow("Operations", ["push(x): add on top", "pop(): remove from top",
                        "peek(): read the top", "isEmpty(): check empty"]),
   _pbul("LIFO Rule", ["Last In, First Out", "Only the top is accessible", "Like a pile of plates"]),
   ["Push adds an item on top.", "Pop removes the top item.", "Peek only reads the top item."],
   _pex("push(1), push(2), push(3),", "pop() returns 3", "So, the stack holds 1 and 2."),
   ["Undo / Redo", "Function Calls", "Browser Back Button", "Expression Evaluation"])

_K(["queue", "queue data structure"],
   "Queue", "A first-in, first-out collection of items.",
   _pflow("Queue Parts", ["Front (remove here)", "Elements", "Rear (add here)"]),
   _pflow("Operations", ["enqueue(x): add at rear", "dequeue(): remove from front",
                        "peek(): read the front", "isEmpty(): check empty"]),
   _pbul("FIFO Rule", ["First In, First Out", "Insert at rear, remove at front", "Like a ticket line"]),
   ["Enqueue adds at the rear.", "Dequeue removes from the front.", "Order of arrival is preserved."],
   _pex("enqueue(1), enqueue(2), enqueue(3),", "dequeue() returns 1", "So, the queue holds 2 and 3."),
   ["Printer Jobs", "CPU Scheduling", "Customer Support", "Breadth-First Search"])

_K(["linked list", "linkedlist"],
   "Linked List", "Nodes connected one after another by pointers.",
   _pflow("List Parts", ["Head", "Node (data + next)", "Tail (next = null)"]),
   _pflow("Operations", ["Create a new node", "Point it to the next node",
                        "Update the previous pointer", "Traverse using next"]),
   _pbul("Key Facts", ["Nodes are not stored together", "Insert / delete is O(1) at head",
                      "Access by index is O(n)", "Size can grow or shrink"]),
   ["Each node stores data and a pointer.", "Head points to the first node.", "The last node points to null."],
   _pex("List: 10 → 20 → 30,", "Insert 15 after 10", "List: 10 → 15 → 20 → 30."),
   ["Music Playlists", "Undo History", "Memory Management", "Hash Table Chaining"])

_K(["recursion", "recursive function", "recursive"],
   "Recursion", "A function that solves a problem by calling itself.",
   _pflow("Key Parts", ["Base case (stop)", "Recursive case", "Call stack"]),
   _pflow("How It Runs", ["Call the function", "Check the base case", "Call itself, smaller input",
                         "Return values back up"]),
   _pformula("Factorial Example", "n! = n × (n − 1)!",
            [("n!", "Factorial of n"), ("n", "Input number"), ("0!", "Base case = 1")]),
   ["Define a base case that stops it.", "Reduce the problem each call.", "Combine results while returning."],
   _pex("factorial(3) =", "3 × 2 × 1 = 6", "So, factorial(3) returns 6."),
   ["Tree Traversal", "Divide and Conquer", "Maze Solving", "Fibonacci Series"])

_K(["oop", "object oriented programming", "object oriented", "class and object", "classes and objects"],
   "Object-Oriented Programming", "Organises code into objects that hold data and actions.",
   _pflow("Core Concepts", ["Class (blueprint)", "Object (instance)", "Attributes (data)", "Methods (actions)"]),
   _pflow("Four Pillars", ["Encapsulation", "Abstraction", "Inheritance", "Polymorphism"]),
   _pbul("Why Use OOP?", ["Reusable code", "Easy to maintain", "Models real-world things",
                         "Better security of data"]),
   ["Define a class as a blueprint.", "Create objects from the class.", "Call methods to use the objects."],
   _pex("Class Car, object myCar,", "myCar.drive()", "So, the object runs its method."),
   ["Game Development", "Banking Software", "Web Frameworks", "Mobile Apps"])

_K(["sql", "database", "dbms", "relational database", "mysql"],
   "SQL and Databases", "Stores data in tables and reads it with queries.",
   _pflow("Database Parts", ["Tables", "Rows (records)", "Columns (fields)", "Primary key"]),
   _pflow("Query Flow", ["Write the SQL query", "Parser checks the syntax", "Optimizer picks a plan",
                        "Engine reads the tables", "Result set is returned"]),
   _pformula("Basic Query", "SELECT col FROM table WHERE x",
            [("SELECT", "Choose columns"), ("FROM", "Choose the table"), ("WHERE", "Filter the rows")]),
   ["Store data in tables.", "Link tables with keys.", "Query data with SQL."],
   _pex("Students with marks above 80:", "SELECT name FROM students WHERE marks>80",
       "So, only top scorers appear."),
   ["Banking", "E-commerce", "Hospital Records", "School Management"])

_K(["computer network", "networking", "tcp ip", "osi model", "internet", "network"],
   "Computer Networks", "Devices connected to share data with each other.",
   _pflow("TCP/IP Layers", ["Application layer", "Transport layer", "Internet layer", "Network access layer"]),
   _pflow("Data Journey", ["Sender creates the data", "Data split into packets",
                          "Routers forward packets", "Receiver reassembles data"]),
   _pbul("Key Devices", ["Router: connects networks", "Switch: connects devices",
                        "Modem: connects to the ISP", "Firewall: filters traffic"]),
   ["Data is split into small packets.", "Each packet finds its own route.", "The receiver puts packets in order."],
   _pex("Opening a website,", "Browser → DNS → Web server", "So, the page appears on screen."),
   ["Internet Browsing", "Video Calls", "Cloud Computing", "Online Banking"])

_K(["atom", "atomic structure", "structure of atom"],
   "The Atom", "The smallest unit of an element.",
   _pflow("Atom Parts", ["Nucleus (centre)", "Protons (+ charge)", "Neutrons (no charge)", "Electrons (− charge)"]),
   _pflow("How It Is Built", ["Protons + neutrons: nucleus", "Electrons orbit in shells",
                             "Protons = electrons", "So the atom is neutral"]),
   _pformula("Mass Number", "A = Z + N",
            [("A", "Mass number"), ("Z", "Atomic number (protons)"), ("N", "Number of neutrons")]),
   ["The nucleus holds protons and neutrons.", "Electrons move in energy shells.",
    "Atomic number = number of protons."],
   _pex("Carbon: Z = 6, N = 6,", "A = 6 + 6 = 12", "So, the mass number is 12."),
   ["Nuclear Energy", "Medical Imaging", "Chemistry", "Electronics"])

_K(["solar system", "planets", "planet"],
   "The Solar System", "The Sun and everything that moves around it.",
   _pflow("Main Members", ["Sun (a star)", "Inner rocky planets", "Asteroid belt", "Outer giant planets"]),
   _pflow("Order from the Sun", ["Mercury, Venus", "Earth, Mars", "Jupiter, Saturn",
                                "Uranus, Neptune", "Dwarf planets and comets"]),
   _pbul("Key Facts", ["8 planets orbit the Sun", "Sun holds 99.8% of the mass",
                      "Earth is the 3rd planet", "Jupiter is the largest planet"]),
   ["Gravity keeps planets in orbit.", "Planets move around the Sun.", "One orbit of Earth = one year."],
   _pex("Sunlight travels to Earth in", "About 8 minutes 20 seconds", "So, we see the Sun slightly in the past."),
   ["Space Missions", "Astronomy", "Satellite Navigation", "Calendars"])

_K(["respiration", "cellular respiration", "aerobic respiration"],
   "Cellular Respiration", "Cells release energy from glucose using oxygen.",
   _pflow("Inputs and Outputs", ["Glucose", "Oxygen", "Mitochondria", "ATP (energy)"]),
   _pflow("Stages", ["Glycolysis (cytoplasm)", "Krebs cycle (mitochondria)",
                    "Electron transport chain", "ATP is released"]),
   _pformula("Equation", "Glucose + O₂ → CO₂ + H₂O + ATP",
            [("O₂", "Oxygen"), ("CO₂", "Carbon dioxide"), ("ATP", "Energy molecule")]),
   ["Glucose is broken down.", "Oxygen helps release energy.", "CO₂ and water leave the cell."],
   _pex("1 glucose molecule gives", "About 30–32 ATP", "So, cells get usable energy."),
   ["Sports Science", "Medicine", "Health Care", "Ecology"])

_K(["food chain", "food web", "ecosystem"],
   "Food Chain", "Shows who eats whom and how energy moves.",
   _pflow("Food Chain", ["Sun", "Producers (plants)", "Primary consumers", "Secondary consumers", "Decomposers"]),
   _pflow("Energy Flow", ["Producers capture 100%", "About 10% passes up",
                         "Rest is lost as heat", "Decomposers recycle matter"]),
   _pbul("Key Terms", ["Producer: makes its own food", "Consumer: eats other organisms",
                      "Decomposer: breaks down dead matter", "Food web: linked food chains"]),
   ["Plants make food using sunlight.", "Animals eat plants or other animals.",
    "Decomposers return nutrients to soil."],
   _pex("Grass → Rabbit → Fox,", "Grass 1000 J → Rabbit 100 J", "So, the fox gets about 10 J."),
   ["Wildlife Conservation", "Agriculture", "Fisheries", "Climate Science"])

_K(["mitosis", "cell division"],
   "Mitosis", "One cell divides into two identical cells.",
   _pflow("Phases", ["Prophase", "Metaphase", "Anaphase", "Telophase"]),
   _pflow("Cell Division", ["Interphase: DNA is copied", "Mitosis: nucleus divides",
                           "Cytokinesis: cell splits", "Two identical new cells"]),
   _pbul("Key Facts", ["One cell becomes two cells", "Daughter cells are identical",
                      "Used for growth and repair", "Chromosome number stays the same"]),
   ["Chromosomes line up in the middle.", "Sister chromatids are pulled apart.", "Two new nuclei form."],
   _pex("A cell with 46 chromosomes", "Divides by mitosis", "Each new cell has 46 chromosomes."),
   ["Wound Healing", "Growth", "Tissue Culture", "Cancer Research"])


# ------------------------------------------------------------- text helpers

def _norm(text):
    """lower-case, drop apostrophes/punctuation, naive singular: "Newton's Laws" -> "newton law"."""
    text = (text or "").lower().replace("’", "").replace("'", "")
    words = []
    for w in re.findall(r"[a-z0-9]+", text):
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def _shorten(text, n, strict=False):
    """Cut text to <= n characters at a clause/word boundary (no ugly mid-word cuts).
    strict=True: return None if the text cannot be cut at a clause boundary."""
    text = re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".")
    if len(text) <= n:
        return text
    cut = text[:n]
    m = max(cut.rfind(","), cut.rfind(";"), cut.rfind(" – "), cut.rfind(" - "))
    if m >= n * 0.5:
        cut = cut[:m]
    elif strict:
        return None
    elif " " in cut:
        cut = cut[:cut.rfind(" ")]
    for _ in range(3):
        cut = re.sub(r"\b(and|or|the|a|an|of|to|in|on|for|with|that|which|is|are|as|by|from)$",
                     "", cut.strip(), flags=re.IGNORECASE).strip(" ,;:-–")
    return cut or text[:n]


def _nice_title(topic):
    words = [w[:1].upper() + w[1:] if w.islower() else w for w in (topic or "").split()]
    return _shorten(" ".join(words), 30) or "Topic"


# ------------------------------------------------------------ topic matching

_INDEX = []     # (normalised alias, kb entry)
for _entry in _KB:
    for _alias in _entry["aliases"]:
        _INDEX.append((_norm(_alias), _entry))


def _find_kb(norm):
    """Exact -> 'alias inside topic' -> typo-tolerant match. Returns a KB entry or None."""
    if not norm:
        return None
    for alias, entry in _INDEX:
        if alias == norm:
            return entry

    words = norm.split()
    padded = f" {norm} "
    best, best_len = None, 0
    for alias, entry in _INDEX:
        if f" {alias} " in padded:
            alias_words = len(alias.split())
            if alias_words / len(words) >= 0.5 and len(alias) > best_len:
                best, best_len = entry, len(alias)
    if best:
        return best

    best, best_ratio = None, 0.0           # typo tolerance: "photosynthsis", "linier regression"
    for alias, entry in _INDEX:
        if len(alias) < 5:                  # short aliases (oop, dna, sql, ml...) must match exactly
            continue
        k = len(alias.split())
        for i in range(0, max(1, len(words) - k + 1)):
            window = " ".join(words[i:i + k])
            ratio = difflib.SequenceMatcher(None, window, alias).ratio()
            if ratio > best_ratio and k / len(words) >= 0.5:
                best, best_ratio = entry, ratio
    return best if best_ratio >= 0.84 else None


# ---------------------------------------------------- category templates

_CATS = {
    "programming": dict(
        words=["code", "coding", "program", "programming", "algorithm", "function", "loop", "variable",
               "array", "string", "class", "object", "python", "java", "javascript", "html", "css", "api",
               "software", "data structure", "compiler", "web", "app", "git", "framework", "flask", "react"],
        sub="{t} explained simply, step by step.",
        parts=("Key Parts", ["Input", "{t}", "Logic / steps", "Output"]),
        proc=("How It Runs", ["Read the input", "Apply {t}", "Process step by step", "Return the result"]),
        key=("Key Ideas", ["Break the problem into steps", "Use clear names and structure",
                           "Test with small inputs", "Reuse code where possible"]),
        steps=["Understand the problem.", "Write the logic as steps.", "Code it and test it."],
        ex=("Example flow:", "Input → Process → Output", "Try it with your own data."),
        apps=["Web Development", "Data Analysis", "Mobile Apps", "Automation"]),
    "math": dict(
        words=["equation", "theorem", "formula", "algebra", "geometry", "trigonometry", "calculus",
               "derivative", "integral", "matrix", "vector", "number", "fraction", "angle", "triangle",
               "circle", "area", "volume", "sine", "cosine", "tangent", "logarithm", "polynomial", "set",
               "statistic", "graph", "function", "ratio", "percentage", "interest"],
        sub="{t}: the main rule and how to use it.",
        parts=("Key Terms", ["{t}", "Given values", "Formula or rule", "Answer"]),
        proc=("Solving Steps", ["Read the problem", "Write the given data", "Apply the formula",
                                "Simplify", "Check the answer"]),
        key=("Remember", ["Learn the formula first", "Check units and signs", "Practise with examples",
                          "Verify the answer"]),
        steps=["Identify what is given.", "Apply the correct rule.", "Check that the answer makes sense."],
        ex=("Solve step by step:", "Given → Formula → Answer", "Always check your answer."),
        apps=["Engineering", "Science", "Finance", "Computer Graphics"]),
    "biology": dict(
        words=["cell", "organ", "system", "plant", "animal", "tissue", "gene", "bacteria", "virus", "blood",
               "brain", "bone", "muscle", "disease", "hormone", "enzyme", "species", "evolution",
               "nervous", "reproduction", "immunity", "lung", "kidney", "liver", "eye", "ear", "skeleton",
               "organism", "protein", "vitamin"],
        sub="{t}: structure, function and why it matters.",
        parts=("Key Parts", ["{t}", "Main structures", "Supporting parts", "End product"]),
        proc=("How It Works", ["Input or stimulus", "Organs / cells respond", "Chemical changes happen",
                               "Products are made", "Waste is removed"]),
        key=("Key Facts", ["Every living thing is affected", "Works together with other systems",
                           "Needs energy to function", "Can be harmed by disease"]),
        steps=["Identify the main parts.", "See how they work together.", "Link structure to function."],
        ex=("In the human body,", "Cause → Response → Result", "So, the body stays healthy."),
        apps=["Medicine", "Agriculture", "Biotechnology", "Health Care"]),
    "physics": dict(
        words=["force", "energy", "motion", "light", "sound", "wave", "heat", "electric", "magnet",
               "gravity", "pressure", "velocity", "power", "current", "optics", "lens", "nuclear",
               "momentum", "speed", "acceleration", "friction", "work", "temperature", "reflection",
               "refraction", "thermodynamic", "semiconductor", "circuit"],
        sub="{t}: the idea, the rule and where it is used.",
        parts=("Key Quantities", ["{t}", "Cause (force / source)", "Effect (change)", "Unit of measure"]),
        proc=("Cause and Effect", ["Identify the system", "Find the forces / energy", "Apply the law",
                                   "Calculate the result", "Check the units"]),
        key=("Key Ideas", ["Nature follows fixed laws", "Energy is never lost", "Measure with correct units",
                           "Experiments confirm theory"]),
        steps=["Name the quantities involved.", "Apply the physical law.", "Calculate and check units."],
        ex=("Everyday example:", "Cause → Law → Effect", "So, we can predict what happens."),
        apps=["Engineering", "Transport", "Electronics", "Space Science"]),
    "chemistry": dict(
        words=["acid", "base", "salt", "reaction", "element", "compound", "molecule", "bond", "periodic",
               "metal", "oxidation", "solution", "mixture", "ion", "organic", "chemical", "catalyst",
               "ph", "alkali", "polymer", "gas", "mole", "isotope", "electrolysis"],
        sub="{t}: what it is and how substances change.",
        parts=("Key Terms", ["{t}", "Reactants", "Conditions", "Products"]),
        proc=("Reaction Steps", ["Reactants are mixed", "Bonds break", "New bonds form",
                                 "Products are formed", "Energy is released / absorbed"]),
        key=("Key Facts", ["Matter is made of atoms", "Mass is conserved", "Reactions change substances",
                           "Balanced equations matter"]),
        steps=["Write the reactants.", "Balance the equation.", "Identify the products."],
        ex=("Simple example:", "Reactants → Products", "So, new substances are formed."),
        apps=["Medicine", "Food Industry", "Agriculture", "Materials"]),
    "history": dict(
        words=["war", "revolution", "empire", "dynasty", "independence", "movement", "ancient", "medieval",
               "king", "treaty", "colonial", "civilization", "history", "freedom", "battle", "mughal",
               "british", "world war", "renaissance", "industrial revolution", "cold war", "queen",
               "emperor", "constitution"],
        sub="{t}: causes, key events and effects.",
        parts=("Key Facts", ["{t}", "Time period", "Key people", "Main places"]),
        proc=("Timeline", ["Background and causes", "Key events begin", "Turning point",
                           "Outcome", "Long-term effects"]),
        key=("Why It Matters", ["Shaped later events", "Changed society and politics",
                                "Led to new ideas", "Still studied today"]),
        steps=["Learn the causes.", "Follow the main events in order.", "Understand the results."],
        ex=("Cause and effect:", "Cause → Event → Effect", "So, history shapes the present."),
        apps=["Understanding Politics", "Culture", "Law and Rights", "Education"]),
    "geography": dict(
        words=["river", "mountain", "climate", "earthquake", "volcano", "ocean", "soil", "continent",
               "monsoon", "weather", "rock", "desert", "forest", "map", "population", "tsunami", "glacier",
               "plate", "erosion", "atmosphere", "latitude", "longitude", "season", "agriculture"],
        sub="{t}: how it forms and why it matters.",
        parts=("Key Features", ["{t}", "Location", "Natural causes", "Human impact"]),
        proc=("How It Forms", ["Natural forces act", "Changes build up", "Landform / event appears",
                               "People adapt", "Environment responds"]),
        key=("Key Facts", ["Affects climate and life", "Changes over long time", "Found in many regions",
                           "Linked to human activity"]),
        steps=["Learn where it occurs.", "Understand how it forms.", "See how it affects people."],
        ex=("Case study:", "Cause → Process → Impact", "So, nature and people interact."),
        apps=["Disaster Planning", "Agriculture", "Tourism", "Urban Planning"]),
    "social": dict(
        words=["demand", "supply", "market", "inflation", "gdp", "trade", "tax", "bank", "profit", "budget",
               "economy", "money", "business", "government", "democracy", "election", "law", "right",
               "citizen", "parliament", "company", "investment", "marketing", "management"],
        sub="{t}: key idea, how it works and examples.",
        parts=("Key Players", ["{t}", "People / groups", "Rules / policies", "Outcome"]),
        proc=("How It Works", ["Need or problem appears", "Decision is made", "Action is taken",
                               "Results are measured", "Adjustments follow"]),
        key=("Key Ideas", ["Choices have costs and benefits", "Rules guide behaviour",
                           "Everyone is affected", "Balance is important"]),
        steps=["Understand the basic idea.", "See who is involved.", "Study the results."],
        ex=("Everyday example:", "Need → Decision → Result", "So, the system keeps working."),
        apps=["Business", "Government", "Banking", "Daily Life"]),
    "general": dict(
        words=[],
        sub="A quick visual overview of {t}.",
        parts=("Key Parts", ["{t}", "Main idea", "Important parts", "Result"]),
        proc=("The Process", ["Start with the basics", "Understand the main idea", "See how parts connect",
                              "Apply it to examples", "Review and practise"]),
        key=("Key Ideas", ["Start with the definition", "Learn the main parts", "Connect it to examples",
                           "Practise with questions"]),
        steps=["Learn the basic idea.", "Apply it to a problem.", "Check your result."],
        ex=("Think of a real example:", "Idea → Practice → Result", "So, understanding grows with practice."),
        apps=["Education", "Industry", "Research", "Daily Life"]),
}
for _c in _CATS.values():
    _c["nwords"] = [_norm(w) for w in _c["words"]]


def _category(norm):
    padded = f" {norm} "
    best, best_hits = "general", 0
    for name, cat in _CATS.items():
        hits = sum(1 for w in cat["nwords"] if w and f" {w} " in padded)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


# ---------------------------------------------------- Wikipedia facts (optional)

def _wikipedia_facts(topic, norm):
    """Plain text from Wikipedia (an ordinary search + text extract, NOT AI).
    Returns a list of cleaned sentences, or None (offline / no match / disabled)."""
    if os.getenv("TUTOR_DIAGRAM_WIKI", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    if not re.search(r"[A-Za-z]{3}", topic or ""):
        return None
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": topic, "gsrlimit": "1", "prop": "extracts",
        "exintro": "1", "explaintext": "1", "exsentences": "8", "redirects": "1",
    }
    request = urllib.request.Request(
        "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "EduVisionTutor/1.0 (educational project)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
        pages = list(((data.get("query") or {}).get("pages") or {}).values())
    except Exception as exc:
        logger.info("Wikipedia lookup skipped: %s", exc)
        return None
    if not pages:
        return None
    page = pages[0]
    extract = page.get("extract") or ""
    if not extract or "may refer to" in extract[:300]:
        return None

    topic_words, title_norm = set(norm.split()), _norm(page.get("title", ""))
    overlap = topic_words & set(title_norm.split())
    if not overlap and difflib.SequenceMatcher(None, norm, title_norm).ratio() < 0.7:
        return None

    text = re.sub(r"\([^)]*\)", "", extract)
    text = re.sub(r"\s+", " ", text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)]
    sentences = [s for s in sentences if 25 <= len(s) <= 400]
    return sentences or None


def _generic_spec(topic, norm):
    cat = _CATS[_category(norm)]
    title = _nice_title(topic)
    short = _shorten(title, 26)

    def fill(s):
        return s.replace("{t}", short)

    facts = _wikipedia_facts(topic, norm)
    subtitle = _shorten(facts[0], 80) if facts else _shorten(fill(cat["sub"]), 80)

    if facts and len(facts) >= 2:
        picked = [_shorten(s, 55, strict=True) for s in facts[1:]]
        key_panel = _pbul("Key Facts", [p for p in picked if p and len(p) > 15][:4])
        if len(key_panel["items"]) < 2:
            key_panel = _pbul(cat["key"][0], cat["key"][1])
    else:
        key_panel = _pbul(cat["key"][0], cat["key"][1])

    return {
        "title": title,
        "subtitle": subtitle,
        "panels": [
            _pflow(cat["parts"][0], [fill(i) for i in cat["parts"][1]]),
            _pflow(cat["proc"][0], [fill(i) for i in cat["proc"][1]]),
            key_panel,
            _psteps(cat["steps"]),
            _pex(*cat["ex"]),
            _pbul("Applications", cat["apps"]),
        ],
    }


# ---------------------------------------------------------------- public API

def build_infographic_spec(topic, question="", topic_hint=None):
    """Return the infographic content for `topic` using plain Python rules. Never raises."""
    try:
        topic = (topic or "").strip() or (topic_hint or "").strip() or "Topic"
        norm = _norm(topic)
        entry = _find_kb(norm)
        if entry is None and question:
            entry = _find_kb(_norm(question))
        if entry is not None:
            return {"title": entry["title"], "subtitle": entry["subtitle"],
                    "panels": copy.deepcopy(entry["panels"])}
        return _generic_spec(topic, norm)
    except Exception:
        logger.exception("Infographic engine error, using the plain template")
        return _generic_spec("Topic", "topic")


def _spec_summary(spec):
    """Short text description of the infographic (given to the chat AI so its explanation matches)."""
    lines = [f"Infographic title: {spec['title']}"]
    for p in spec["panels"]:
        t = p["type"]
        if t == "chart":
            body = "a chart of data points" + (" with a best-fit line" if p.get("line") else "")
        elif t == "formula":
            legend = ", ".join(f"{a} = {b}" for a, b in p.get("legend", []))
            body = p["formula"] + (f" ({legend})" if legend else "")
        elif t == "example":
            body = " ".join(x for x in (p.get("intro"), p.get("calc"), p.get("result")) if x)
        else:
            body = "; ".join(p.get("items", []))
        lines.append(f"- {p['heading']}: {body}")
    return "\n".join(lines)[:1500]


def _spec_to_markdown(spec):
    """Offline explanation built from the diagram itself (used when the chat AI is unavailable)."""
    out = [f"## {spec['title']}"]
    if spec.get("subtitle"):
        out.append(f"*{spec['subtitle']}*")
    for p in spec["panels"]:
        t, head = p["type"], p.get("heading") or ""
        if t == "chart":
            out.append(f"**{head}**: the chart plots the data points"
                       + (" and the best-fit line through them." if p.get("line") else "."))
        elif t == "formula":
            lines = [f"**{head}**: `{p['formula']}`"]
            lines += [f"- `{a}`: {b}" for a, b in p.get("legend", [])]
            out.append("\n".join(lines))
        elif t == "example":
            parts = [x for x in (p.get("intro"), p.get("calc"), p.get("result")) if x]
            out.append(f"**{head}**: " + " ".join(parts))
        else:
            out.append(f"**{head}**\n" + "\n".join(f"- {i}" for i in p.get("items", [])))
    return "\n\n".join(out)


_PANEL_WHERE = ["top left", "top middle", "top right", "bottom left", "bottom middle", "bottom right"]
_PANEL_COLOUR = ["blue", "green", "purple", "orange", "green", "red"]   # header colours used by the drawing


def _spec_walkthrough(spec):
    """Plain-language guide to the DRAWING: what every box shows and how to read it.
    Built from the same data the SVG is drawn from, so it always matches the picture."""
    title = spec["title"]
    out = ["### How to read this diagram", ""]
    intro = (f"The picture is a poster with a dark blue title bar that says **{title}**")
    if spec.get("subtitle"):
        intro += f", and one line under it: *{spec['subtitle'].rstrip('.!?, ')}*"
    intro += (". Below are six boxes. Read the top row from left to right, "
              "then the bottom row from left to right.")
    out += [intro, ""]

    for n, p in enumerate(spec["panels"][:6]):
        t, head = p["type"], (p.get("heading") or f"Box {n + 1}")
        where, colour = _PANEL_WHERE[n], _PANEL_COLOUR[n]
        out.append(f"**{n + 1}. {head}** ({where}, {colour} header)")
        out.append("")
        items = p.get("items", [])
        if t == "flow":
            chain = " \u2192 ".join(items)
            out.append(f"Boxes joined by small arrows. Follow them from top to bottom: {chain}. "
                       "Each box is one stage, and the arrow shows what comes next.")
        elif t == "steps":
            steps = " ".join(f"({k}) {x}" for k, x in enumerate(items, 1))
            out.append(f"Numbered orange circles show the order. Do them one by one: {steps}")
        elif t == "formula":
            out.append(f"The shaded box holds the formula `{p['formula']}`.")
            if p.get("legend"):
                out.append("Under it, each symbol is explained:")
                out += [f"- `{a}` means {b}" for a, b in p["legend"]]
        elif t == "example":
            def _t(x):
                return str(x).strip().rstrip(".,;: ")
            parts = []
            if p.get("intro"):
                parts.append(f"it starts with: {_t(p['intro'])}")
            if p.get("calc"):
                parts.append(f"the working is `{_t(p['calc'])}`")
            if p.get("result"):
                parts.append(f"the answer is: {_t(p['result'])}")
            body = "; ".join(parts)
            out.append("A worked example. " + body[:1].upper() + body[1:] + ".")
        elif t == "chart":
            xl, yl = p.get("x_label") or "the horizontal values", p.get("y_label") or "the vertical values"
            text = (f"A graph. The bottom line (x-axis) shows {xl}, and the side line (y-axis) shows {yl}. "
                    f"Each dot is one data point ({len(p.get('points', []))} in total).")
            if p.get("line"):
                text += (f" The straight line, labelled \"{p.get('line_label') or 'Best-fit line'}\", "
                         "runs through the dots and shows the overall trend.")
            out.append(text)
        else:
            out.append("Green ticks mark the key points: " + "; ".join(items) + ".")
        if n == 0 and len(spec["panels"]) >= 2:
            out.append("")
            out.append("The thick arrow between box 1 and box 2 means: first understand the parts, "
                       "then see how they work together.")
        out.append("")

    out.append("**Putting it together:** start with the big picture in box 1, follow the process in "
               "box 2, then use the middle and bottom boxes to see the details, a worked example "
               "and where the idea is used. Tap the picture to open it full screen.")
    return "\n".join(out)


def make_infographic(topic, question, topic_hint=None):
    """Build the infographic with the PYTHON engine (no Ollama, no Gemini), draw it, save it.
    Returns {'title', 'url', 'spec'}, or None only if the file cannot be written."""
    spec = None
    try:
        spec = _clean_spec(build_infographic_spec(topic, question, topic_hint))
    except Exception:
        logger.exception("Infographic engine failed")
    if not spec:
        title = (topic or "Topic").title()[:34]
        spec = {"title": title, "subtitle": _s(f"Quick visual overview of {topic}.", 90),
                "panels": _default_panels(title)}
    try:
        url = save_infographic(render_infographic_svg(spec), topic)
        return {"title": spec["title"], "url": url, "spec": spec}
    except Exception:
        logger.exception("Could not save infographic")
        return None


# ------------------------------------------------------ Wikimedia image search
# (used only if the infographic file could not be saved)

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/svg+xml", "image/gif"}
_BAD_TITLE_WORDS = ("logo", "icon", "flag", "map of", "signature", "stamp")


def find_diagram_images(topic, limit=MAX_IMAGES):
    """Search Wikimedia Commons for diagram images of `topic`.
    Returns [{'title', 'url', 'page'}]. Never raises: returns [] on any problem."""
    if not topic:
        return []

    api = "https://commons.wikimedia.org/w/api.php"
    results = []
    for search in (f"{topic} diagram", topic):      # diagram first, then plain
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search,
            "gsrnamespace": "6",                    # File: namespace
            "gsrlimit": "12",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "800",
        }
        request = urllib.request.Request(
            api + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": "EduVisionTutor/1.0 (educational project)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Image search failed: %s", exc)
            return results

        pages = (data.get("query") or {}).get("pages") or {}
        for page in sorted(pages.values(), key=lambda p: p.get("index", 999)):
            info = (page.get("imageinfo") or [{}])[0]
            title = page.get("title", "")
            if info.get("mime") not in _ALLOWED_MIME:
                continue
            if any(bad in title.lower() for bad in _BAD_TITLE_WORDS):
                continue
            url = info.get("thumburl") or info.get("url")
            if not url or any(r["url"] == url for r in results):
                continue
            nice = re.sub(r"^File:", "", title)
            nice = re.sub(r"\.\w+$", "", nice).replace("_", " ")
            nice = re.sub(r"[\[\]()]", "", nice)    # keep Markdown links valid
            results.append({"title": nice, "url": url,
                            "page": info.get("descriptionurl", url)})
            if len(results) >= limit:
                return results
        if results:
            break
    return results


def _images_markdown(images):
    parts = [IMAGE_MARKER + "\n"]
    for img in images:
        parts.append(
            f"![{img['title']}]({img['url']})\n\n"
            f"*{img['title']}* - [source: Wikimedia Commons]({img['page']})\n"
        )
    return "\n".join(parts)


def _infographic_markdown(info):
    title = re.sub(r"[\[\]()]", "", info["title"])
    return (
        IMAGE_MARKER + "\n\n"
        f"![{title}]({info['url']})\n\n"
        f"*{title}* - [open full size]({info['url']})\n"
    )


# ------------------------------------------------------------- AI providers

def _ollama_chat(messages, json_mode=False, max_tokens=1800, model=None):
    url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    model = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    timeout = int(os.getenv("TUTOR_TIMEOUT", "180"))

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.3 if json_mode else 0.5,
                    "num_ctx": 8192, "num_predict": max_tokens},
    }
    if json_mode:
        payload["format"] = "json"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")[:300]
        logger.error("Ollama HTTP %s: %s", exc.code, details)
        if exc.code == 404:
            raise TutorError(
                f"The AI model '{model}' is not installed. "
                f"Open a terminal and run: ollama pull {model}"
            ) from exc
        raise TutorError("The AI service returned an error. Please try again.") from exc
    except TimeoutError as exc:
        raise TutorError(
            "The AI took too long to answer. Try a shorter question or ask again."
        ) from exc
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise TutorError(
                "The AI took too long to answer. Try a shorter question or ask again."
            ) from exc
        logger.error("Ollama is not reachable: %s", exc)
        raise _ProviderUnavailable(str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise TutorError("The AI sent an unreadable reply. Please try again.") from exc

    return (result.get("message") or {}).get("content", "") or ""


def _gemini_chat(messages):
    """Fallback that reuses your existing ai_service.call_model(prompt)."""
    import ai_service  # project root; same module learning.py already uses

    lines = []
    for message in messages:
        if message["role"] == "system":
            lines.append(message["content"])
        elif message["role"] == "user":
            lines.append("Student: " + message["content"])
        else:
            lines.append("Tutor: " + message["content"])
    lines.append("Tutor:")
    return ai_service.call_model("\n\n".join(lines)) or ""


def _llm(messages, json_mode=False, max_tokens=1800, model=None):
    """Ollama first; Gemini only if Ollama is unreachable and a key exists.
    `model` overrides OLLAMA_MODEL for this one call (used for diagrams)."""
    try:
        return _ollama_chat(messages, json_mode=json_mode, max_tokens=max_tokens, model=model)
    except _ProviderUnavailable:
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            try:
                return _gemini_chat(messages)
            except Exception:
                logger.exception("Gemini fallback failed")
                raise TutorError(
                    "The AI tutor is not available right now. Please try again in a moment."
                )
        raise TutorError(
            "Cannot connect to the AI service. Make sure Ollama is running "
            "(open the Ollama app, or run: ollama serve), then try again."
        )


# ----------------------------------------------------------------- main API

def ask_tutor(question, history=None, video_context=None, topic_hint=None):
    """Return the tutor's answer (Markdown text). Raises TutorError with a friendly message.

    video_context: optional lesson text (title, script...) added to the system prompt.
    topic_hint:    optional fallback topic for the diagram (e.g. the video title).
    If the student asks for an image/diagram, a Python-made infographic is attached.
    """
    question = (question or "").strip()
    if not question:
        raise TutorError("Please type a question.")

    system_prompt = SYSTEM_PROMPT
    if isinstance(video_context, str) and video_context.strip():
        system_prompt += "\n\n" + video_context.strip()[:MAX_CONTEXT_CHARS]

    # 1) image request? draw the infographic with the Python engine (no AI needed)
    infographic, images = None, []
    if wants_image(question):
        topic = extract_topic(question, history, topic_hint)
        infographic = make_infographic(topic, question, topic_hint)
        if not infographic:
            images = find_diagram_images(topic)         # last resort only
        if infographic:
            system_prompt += (IMAGE_HINT_INFOGRAPHIC
                              + "\n\nThe attached infographic contains:\n"
                              + _spec_summary(infographic["spec"]))
        else:
            system_prompt += IMAGE_HINT_WITH_IMAGES if images else IMAGE_HINT_NO_IMAGES

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(clean_history(history))
    messages.append({"role": "user", "content": question[:MAX_QUESTION_CHARS]})

    # 2) text explanation from the chat AI (if it is offline, the diagram still works)
    try:
        answer = (_llm(messages) or "").strip()
        if not answer:
            raise TutorError("The AI returned an empty answer. Please rephrase and try again.")
    except TutorError:
        if infographic:
            # chat AI offline: the panel-by-panel guide below explains the whole drawing
            sp = infographic["spec"]
            answer = f"## {sp['title']}" + (f"\n\n*{sp['subtitle']}*" if sp.get("subtitle") else "")
        else:
            raise

    # 3) attach the diagram
    if infographic:
        answer += _infographic_markdown(infographic)
        try:
            answer += "\n\n" + _spec_walkthrough(infographic["spec"])
        except Exception:
            logger.exception("Could not build the diagram walkthrough")
    elif images:
        answer += _images_markdown(images)
    return answer