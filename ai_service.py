"""
ai_service.py
All the Generative AI work for the video quiz and the "ask a question" feature.
Needs in .env:   GEMINI_API_KEY=your_key
Install once:    pip install google-genai
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def call_model(prompt):
    """Sends a prompt to the AI and returns the reply as text.
    If your test_gemini.py uses a different library or model name,
    copy the same lines here instead."""
    from google import genai
    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(model=MODEL, contents=prompt)
    return response.text


def answer_question(context, question):
    """Answers a student's question using the video content."""
    prompt = (
        "You are a friendly tutor helping a student who just watched an educational video.\n"
        "Answer the student's question in simple words, in under 120 words.\n"
        "Use the video content below. If the question is not covered in the video, "
        "say that briefly and then give a short, correct general explanation.\n\n"
        "VIDEO CONTENT:\n" + context[:6000] + "\n\n"
        "STUDENT QUESTION:\n" + question
    )
    return call_model(prompt).strip()


def make_quiz(context, count=5):
    """Creates multiple-choice questions from the video content.
    Returns a list like:
    [{"q": "...", "options": ["a","b","c","d"], "answer": "a", "explanation": "..."}]
    Returns an empty list if the AI reply could not be used."""
    prompt = (
        "Create " + str(count) + " multiple-choice quiz questions to test a student's "
        "understanding of the content below. Keep the language simple.\n"
        "Reply with ONLY a JSON array and nothing else. Each item must look like:\n"
        '{"q": "question text", "options": ["A", "B", "C", "D"], '
        '"answer": "the exact text of the correct option", '
        '"explanation": "one short sentence explaining the answer"}\n'
        "Each question must have exactly 4 options and exactly one correct answer.\n\n"
        "CONTENT:\n" + context[:6000]
    )

    for attempt in range(2):                      # try twice if the reply is not valid
        try:
            text = call_model(prompt).strip()
            start = text.find("[")
            end = text.rfind("]")
            items = json.loads(text[start:end + 1])

            good = []
            for item in items:
                options = [str(o) for o in item["options"]]
                answer = str(item["answer"])
                if len(options) == 4 and answer in options:
                    good.append({
                        "q": str(item["q"]),
                        "options": options,
                        "answer": answer,
                        "explanation": str(item.get("explanation", "")),
                    })
            if len(good) >= 3:
                return good
        except Exception as error:
            print("Quiz creation problem:", error)

    return []