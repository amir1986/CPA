"""Print the live KeyRotator state. Used by `make rotator-status`."""

from __future__ import annotations

import json

from app.config import get_settings
from app.llm.ollama_rotator import KeyRotator


def main() -> None:
    settings = get_settings()
    keys = settings.resolved_api_keys()
    if not keys:
        print(json.dumps({"error": "OLLAMA_API_KEYS not set"}))
        return
    rot = KeyRotator(keys, cooldown_seconds=settings.ollama_rate_limit_cooldown_seconds)
    snap = rot.snapshot()
    print(json.dumps({"cursor": snap.cursor, "keys": snap.keys}, indent=2))


if __name__ == "__main__":
    main()
