"""Dump the OpenAPI spec to spec/openapi.json for openapi-typescript drift check."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "spec" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
