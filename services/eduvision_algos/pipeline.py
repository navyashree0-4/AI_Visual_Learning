"""Single entry point: run all own algorithms on a text. Safe to call before the AI; never raises on odd input."""
from .concept_extraction import extract_concepts
from .scene_planner import plan_scenes
from .summarizer import summarize
from .text_preprocessing import preprocess
from .topic_understanding import understand_topic


def analyze(text, n_scenes=7, topic=None):
    info = understand_topic(text, topic)                 # step 0: what is this about?
    topic = info["topic"]
    pre = preprocess(text)
    concepts = extract_concepts(text, top_k=15, pre=pre)
    return {
        "topic_info": info,
        "word_count": pre["word_count"],
        "concepts": concepts,
        "summary": summarize(text, n_sentences=5, simplify=True, pre=pre, concepts=concepts),
        "plan": plan_scenes(text, n_scenes=n_scenes, topic=topic),
    }


def hint_block(analysis):
    """Text to append to the Gemini/Ollama prompt so the AI follows the algorithmic plan (hybrid step)."""
    plan = analysis["plan"]
    info = analysis.get("topic_info") or {}
    lines = [f"DETECTED TOPIC: {info.get('topic', '')} | SUBJECT: {info.get('subject', 'General')} | LEVEL HINT: {info.get('level_hint', '')}",
             "ALGORITHM-DETECTED KEY CONCEPTS (cover the genuinely important ones, ignore awkward phrases): " +
             ", ".join(c["term"] for c in analysis["concepts"][:10]),
             "SUGGESTED SCENE ORDER:"]
    for i, s in enumerate(plan["sections"], 1):
        lines.append(f"{i}. {s['title']} ({s['visual_type']}) - " + "; ".join(s["concepts"]))
    return "\n".join(lines)
