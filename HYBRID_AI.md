# EduVision - Hybrid AI architecture

Pre-trained models and our own Python algorithms work together. Nothing was removed: Gemini, Ollama,
routes, credits, refunds, quiz and video history are unchanged.

| Stage | Done by | Where in the code |
|---|---|---|
| Topic understanding: topic, subject, level (step 0) | **Own algorithm** | `topic_understanding.py` |
| Text cleaning, sentence splitting, stemming | **Own algorithm** | `eduvision_algos/text_preprocessing.py` |
| Concept extraction and ranking (n-grams, definitions, TextRank) | **Own algorithm** | `concept_extraction.py` |
| Scene planning (TextTiling-style segmentation, visual-type rules) | **Own algorithm** | `scene_planner.py` |
| Narration selection / summarization (MMR) | **Own algorithm** | `summarizer.py`, `scene_builder.py` |
| Script wording and real-life examples | **Pre-trained AI** (Gemini, Ollama Llama 3.2) | `_polish_with_ai`, `plan_outline`, `write_scene_batch` |
| Concept validation of AI text | **Own algorithm** | `concept_validator.py` |
| Narration audio | **Pre-trained TTS**: gTTS (`TTS_ENGINE=gtts`) or edge-tts | `generate_narration` |
| Real images | Wikimedia, Wikipedia, Pexels, Pixabay, Openverse | image search functions |
| Animated frames, captions, highlights | **Own code** (Pillow `Painter`) | `video_generator.py` |
| Speed fit, fades, joining, music mix | **Own code** driving FFmpeg | `video_generator.py` |

## Script modes (`EDUVISION_SCRIPT_MODE`)
- `hybrid` (default): algorithms build the scenes, the AI re-words them, the validator rejects invented facts.
- `algo`: algorithms only. `ai`: AI writes everything (algorithms still hint and validate).

## Fallbacks when a model is unavailable
1. Gemini fails -> fallback Gemini models -> Ollama (existing behaviour).
2. Every AI model fails -> our algorithms write the script alone (`script_mode = algo-fallback`).
3. Input is only a short topic and no AI works -> a Wikipedia article is fetched as source text for the algorithms.
4. edge-tts fails -> gTTS. Algorithm error -> normal AI script. No photo -> drawn diagram.
5. Any failed job still refunds the credits.

Each result also carries `script_mode` and `hybrid_report` (which stage used what).
Limits: algorithmic narration is English only; Kannada/Hindi use the AI script.
