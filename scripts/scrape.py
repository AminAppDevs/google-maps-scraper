#!/usr/bin/env python3
"""
Scrape Google Maps directly from the CLI (no n8n, no API server).

Examples:
  python scripts/scrape.py "pet store Riyadh" --max-places 50 --output riyadh-pets.json
  python scripts/scrape.py "عيادة بيطرية جدة" --lang ar --output jeddah-vets.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gmaps_scraper_server.scraper import scrape_google_maps  # noqa: E402


def flatten_place(place: dict) -> dict:
    coords = place.get("coordinates") or {}
    row = dict(place)
    row["latitude"] = coords.get("latitude")
    row["longitude"] = coords.get("longitude")
    row.pop("coordinates", None)
    for key in ("categories", "hours"):
        if isinstance(row.get(key), list):
            row[key] = " | ".join(str(v) for v in row[key])
    return row


def write_json(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    flat = [flatten_place(r) for r in rows]
    if not flat:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in flat:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Google Maps to JSON or CSV")
    parser.add_argument("query", help='Search query, e.g. "pet store Riyadh"')
    parser.add_argument("--max-places", type=int, default=None, help="Cap results (default: all found, up to ~120 per query)")
    parser.add_argument("--lang", default="en", help="Language code (en, ar via hl, etc.)")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--concurrency", type=int, default=5, help="Parallel detail tabs (1-10 recommended)")
    parser.add_argument("-o", "--output", default="results.json", help="Output file (.json or .csv)")
    args = parser.parse_args()

    print(f"Scraping: {args.query!r} (lang={args.lang}, max={args.max_places or 'all'})")
    results = await scrape_google_maps(
        query=args.query,
        max_places=args.max_places,
        lang=args.lang,
        headless=args.headless,
        concurrency=args.concurrency,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".csv":
        write_csv(out, results)
    else:
        write_json(out, results)

    print(f"Saved {len(results)} places to {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
