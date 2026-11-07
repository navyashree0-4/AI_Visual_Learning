"""
services/ai_tutor_service.py

AI Doubt-Solving Tutor: talks to the SAME AI setup EduVision already uses.

Provider used (taken from your project, nothing new is added):
  1. Ollama (local, free)  - OLLAMA_URL and OLLAMA_MODEL from your .env
                             (the same settings services/video_generator.py uses)
  2. Gemini (optional)     - only if GEMINI_API_KEY / GOOGLE_API_KEY is set in .env.
                             It is used through your existing ai_service.call_model()
                             and only when Ollama cannot be reached.

This file never imports app.py and creates no database tables.
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

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

MAX_QUESTION_CHARS = 2000      # one student question
MAX_MESSAGE_CHARS = 4000       # one remembered message (answers can be longer)
MAX_HISTORY_MESSAGES = 12      # how many earlier messages the AI remembers


class TutorError(Exception):
    """An error whose text is safe and helpful to show to the student."""


class _ProviderUnavailable(Exception):
    """Ollama could not be reached (not running, wrong URL, network problem)."""


def clean_history(history):
    """Keep only valid recent messages: [{'role': 'user'|'assistant', 'content': str}]."""
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
        content = content.strip()
        if content:
            cleaned.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    return cleaned


def _ollama_chat(messages):
    url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    timeout = int(os.getenv("TUTOR_TIMEOUT", "180"))

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.5, "num_ctx": 8192, "num_predict": 1800},
    }
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


def ask_tutor(question, history=None):
    """Return the tutor's answer (Markdown text). Raises TutorError with a friendly message."""
    question = (question or "").strip()
    if not question:
        raise TutorError("Please type a question.")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(clean_history(history))
    messages.append({"role": "user", "content": question[:MAX_QUESTION_CHARS]})

    try:
        answer = _ollama_chat(messages)
    except _ProviderUnavailable:
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            try:
                answer = _gemini_chat(messages)
            except Exception:
                logger.exception("Gemini fallback failed")
                raise TutorError(
                    "The AI tutor is not available right now. Please try again in a moment."
                )
        else:
            raise TutorError(
                "Cannot connect to the AI service. Make sure Ollama is running "
                "(open the Ollama app, or run: ollama serve), then try again."
            )

    answer = (answer or "").strip()
    if not answer:
        raise TutorError("The AI returned an empty answer. Please rephrase and try again.")
    return answer