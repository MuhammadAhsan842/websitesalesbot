"""CLIP vs SigLIP vs Ollama image embed. Does not mix MiniLM space."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import vision


def main() -> int:
    report = {
        "clip_space": True,
        "minilm_space": False,
        "image_embed": vision.status(),
        "candidates": ["open_clip:ViT-B-32:openai", "open_clip:ViT-B-16-SigLIP:webli", "ollama:embeddinggemma"],
        "note": "Text queries for images must use this encoder. MiniLM rankings are fused with RRF, never concatenated vectors.",
    }
    try:
        import open_clip  # noqa: F401

        report["open_clip"] = True
    except Exception:
        report["open_clip"] = False
        report["skip"] = "open_clip is not installed; leaving IMAGE_EMBED_MODEL=off is correct until a CLIP checkpoint is qualified."
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
