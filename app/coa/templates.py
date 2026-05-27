"""Default COA templates loaded from config/coa_templates/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CoaTemplateAccount:
    code: str
    name: str
    type: str
    parent_code: str | None = None


def load_template(name: str, *, templates_dir: Path | None = None) -> list[CoaTemplateAccount]:
    templates_dir = templates_dir or Path(__file__).resolve().parents[2] / "config" / "coa_templates"
    path = templates_dir / f"{name}.yaml"
    if not path.exists():
        raise KeyError(f"unknown COA template: {name} (at {path})")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        CoaTemplateAccount(
            code=str(a["code"]),
            name=str(a["name"]),
            type=str(a["type"]),
            parent_code=str(a["parent_code"]) if a.get("parent_code") else None,
        )
        for a in raw.get("accounts", [])
    ]
