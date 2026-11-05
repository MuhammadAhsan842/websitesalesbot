# CPU / admission notes (historical)

Chat inference is **Gemini-only** (`app/llm.py` + `app/gemini.py`). Local Ollama is not used for sales turns.

Admission queue knobs (optional): `LLM_MAX_INFLIGHT`, `LLM_MAX_WAITING`, `LLM_QUEUE_TIMEOUT_SEC`.

Background vision (optional, off by default): `OLLAMA_VISION=on` + `OLLAMA_VISION_MODEL=…`.
