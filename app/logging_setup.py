"""Logging setup: one line per relevant event, never credentials or full payloads."""

from __future__ import annotations

import logging
import sys

SENSITIVE = ("password", "token", "secret", "authorization", "api_key")


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "urllib3", "transformers", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def redact(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in SENSITIVE):
        return "***"
    return value
