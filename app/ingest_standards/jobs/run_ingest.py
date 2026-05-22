"""CLI for the standards-corpus ingest.

Used by:
- ``docker compose run --rm ingest`` (the compose ``ingest`` profile)
- the Helm ``ingest-job.yaml`` / ``ingest-cronjob.yaml``

Usage:

    python -m app.ingest_standards.jobs.run_ingest                       # all sources
    python -m app.ingest_standards.jobs.run_ingest --source fasb_asc_public
    python -m app.ingest_standards.jobs.run_ingest --source iasb_org_il_he --full-resync
    python -m app.ingest_standards.jobs.run_ingest --dry-run             # just print discovery
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Iterable

from app.ingest_standards.discovery import discover_urls
from app.ingest_standards.fetcher import FetchOptions, http_fetch
from app.ingest_standards.pipeline import ingest_source
from app.ingest_standards.registry import Source, get_source, load_sources
from app.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standards corpus ingest.")
    p.add_argument("--source", action="append", help="Source id (may repeat). Default: all sources.")
    p.add_argument("--full-resync", action="store_true", help="Purge then re-ingest.")
    p.add_argument("--dry-run", action="store_true", help="Print discovered URLs and exit.")
    p.add_argument("--global-concurrency", type=int, default=4)
    p.add_argument("--per-host-concurrency", type=int, default=2)
    return p.parse_args(argv)


def _sources_to_run(picked: list[str] | None) -> Iterable[Source]:
    if not picked:
        return load_sources()
    out: list[Source] = []
    for sid in picked:
        try:
            out.append(get_source(sid))
        except KeyError as exc:
            logger.error("unknown source id: %s", sid)
            raise SystemExit(2) from exc
    return out


async def _run_one(source: Source, *, full_resync: bool, dry_run: bool, opts: FetchOptions) -> int:
    logger.info("ingest start: %s (%s, %s, lang=%s)", source.id, source.corpus_type, source.jurisdiction, source.language)
    if dry_run:
        urls = await discover_urls(source, user_agent=opts.user_agent, timeout=opts.timeout)
        print(f"== {source.id} ({len(urls)} urls) ==")
        for u in urls:
            print(f"  {u}")
        return 0

    async def _fetch(s: Source) -> list:
        return await http_fetch(s, opts)

    chunks = await ingest_source(source, fetcher=_fetch, full_resync=full_resync)

    # Increment the ingest counter once we have an answer.
    try:
        from app.telemetry import INGEST_DOCS

        INGEST_DOCS.labels(source_id=source.id).inc(chunks)
    except Exception:
        pass

    logger.info("ingest done: %s — %d chunks upserted", source.id, chunks)
    return chunks


async def main_async() -> int:
    args = _parse_args()
    configure_logging("INFO")

    opts = FetchOptions(
        global_concurrency=args.global_concurrency,
        per_host_concurrency=args.per_host_concurrency,
    )

    total = 0
    for source in _sources_to_run(args.source):
        try:
            total += await _run_one(source, full_resync=args.full_resync, dry_run=args.dry_run, opts=opts)
        except Exception:  # noqa: BLE001 — log and continue with other sources
            logger.exception("ingest failed for %s", source.id)
    return total


def main() -> None:
    chunks = asyncio.run(main_async())
    print(f"upserted {chunks} chunks", file=sys.stderr)


if __name__ == "__main__":
    main()
