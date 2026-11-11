"""Run from your project root:  python test_gemini.py
Times one tiny Gemini call per available flash model, so you can pick the fastest for GEMINI_MODEL."""
import json, os, time, urllib.request, urllib.error
from services import video_generator as vg

KEY = vg.GEMINI_API_KEY
if not KEY:
    raise SystemExit("GEMINI_API_KEY is not set in .env")

req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                             headers={"x-goog-api-key": KEY})
models = [m["name"].split("/", 1)[-1] for m in json.load(urllib.request.urlopen(req, timeout=30))["models"]
          if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]
          and not any(x in m["name"] for x in ("image", "tts", "live", "audio"))]
print("Flash models for your key:", models, "\n")

vg._gemini_discover_model = lambda: None       # test each model as it is, no automatic switching
wanted = [m for m in models if "omni" not in m]
# lite / latest first (fastest), then the rest
wanted.sort(key=lambda m: (0 if ("lite" in m or "latest" in m) else 1, m))
for name in wanted[:10]:
    vg._gemini_model[0] = name
    vg.GEMINI_TIMEOUT = 40
    vg._gemini_off_until[0] = 0
    t = time.time()
    try:
        out = vg._gemini_response('Reply with JSON {"ok": true} only.', num_predict=200)
        print(f"{name:40s} {time.time() - t:5.1f}s  OK  {out[:40]!r}")
    except Exception as exc:
        print(f"{name:40s} {time.time() - t:5.1f}s  FAIL {str(exc)[:80]}")
print("\nPut the fastest OK model in .env as GEMINI_MODEL=gemini-3.5-flash")