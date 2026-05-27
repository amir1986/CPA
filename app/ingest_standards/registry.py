"""Source registry — load and validate config/sources.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    corpus_type: str
    jurisdiction: str
    language: str
    kind: str
    licence: str


def load_sources(path: Path | None = None) -> list[Source]:
    path = path or Path(__file__).resolve().parents[2] / "config" / "sources.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[Source] = []
    for raw in data.get("sources", []):
        out.append(Source(**raw))
    return out


def get_source(source_id: str, path: Path | None = None) -> Source:
    for s in load_sources(path):
        if s.id == source_id:
            return s
    raise KeyError(f"unknown source id: {source_id}")
