"""Download and warm the local models at image build time.

At runtime the plant has no internet: the models must already be on disk.
The ASR model is mandatory; the optional language model is best effort.
"""

from __future__ import annotations

import os
import sys

ASR_MODEL = os.environ.get("ASR_REPO", "Systran/faster-whisper-small")
LLM_MODEL = os.environ.get("LLM_REPO", "Qwen/Qwen2.5-0.5B-Instruct")
ASR_DIR = os.environ.get("ASR_DIR", "/models/faster-whisper-small")
LLM_DIR = os.environ.get("LLM_DIR", "/models/qwen2.5-0.5b-instruct")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")


def main() -> int:
    from huggingface_hub import snapshot_download

    print(f"downloading ASR model {ASR_MODEL}", flush=True)
    snapshot_download(repo_id=ASR_MODEL, local_dir=ASR_DIR)
    if os.environ.get("DOWNLOAD_LLM", "0") == "1":
        try:
            print(f"downloading optional language model {LLM_MODEL}", flush=True)
            snapshot_download(repo_id=LLM_MODEL, local_dir=LLM_DIR)
        except Exception as exc:  # noqa: BLE001
            print(f"optional language model unavailable: {exc}", file=sys.stderr, flush=True)
    try:
        from fastembed import TextEmbedding

        print(f"warming embedding model {EMBEDDING_MODEL}", flush=True)
        next(iter(TextEmbedding(model_name=EMBEDDING_MODEL).embed(["passage: calentamiento"])))
    except Exception as exc:  # noqa: BLE001
        print(f"embedding model unavailable: {exc}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
