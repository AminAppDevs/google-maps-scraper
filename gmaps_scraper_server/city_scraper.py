"""Orchestrate grid-based city-wide Google Maps scraping."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from .dedupe import deduplicate_places
from .grid import SAUDI_CITIES, bbox_from_tuple, generate_grid
from .scraper import scrape_google_maps

logger = logging.getLogger(__name__)

CITY_AR = {
    "Dammam": "الدمام",
    "Riyadh": "الرياض",
    "Jeddah": "جدة",
    "Khobar": "الخبر",
    "Mecca": "مكة",
    "Medina": "المدينة المنورة",
    "Abha": "أبها",
    "Tabuk": "تبوك",
}


def _city_ar(city: str) -> str:
    return CITY_AR.get(city, city)

ProgressCallback = Callable[[Dict[str, Any]], None]

# Keywords for comprehensive pet business coverage
PET_KEYWORDS_EN = ["pet store", "veterinary clinic", "pet grooming"]
PET_KEYWORDS_AR = ["محل حيوانات أليفة", "عيادة بيطرية", "تجميل حيوانات أليفة"]


def keywords_for_lang(lang: str, include_vet: bool = True) -> List[str]:
    if lang == "ar":
        kws = ["محل حيوانات أليفة"]
        if include_vet:
            kws.append("عيادة بيطرية")
        return kws
    kws = ["pet store"]
    if include_vet:
        kws.append("veterinary clinic")
    return kws


async def scrape_city_grid(
    city: str,
    keyword: Optional[str] = None,
    lang: str = "en",
    zoom: int = 15,
    cell_size_km: float = 3.0,
    max_per_cell: int = 120,
    headless: bool = True,
    concurrency: int = 5,
    include_vet_clinics: bool = True,
    pause_between_searches_sec: float = 3.0,
    on_progress: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Scan a city using a geographic grid with zoomed searches.
    Returns dict with results, stats, and meta.
    """
    if city not in SAUDI_CITIES:
        raise ValueError(f"Unknown city: {city}. Available: {', '.join(SAUDI_CITIES)}")

    bbox = bbox_from_tuple(SAUDI_CITIES[city])
    cells = generate_grid(bbox, cell_size_km)

    if keyword:
        search_keywords = [keyword]
    else:
        search_keywords = keywords_for_lang(lang, include_vet=include_vet_clinics)

    total_steps = len(cells) * len(search_keywords)
    all_places: List[Dict[str, Any]] = []
    step = 0

    def emit(payload: Dict[str, Any]) -> None:
        if on_progress:
            on_progress(payload)

    emit({
        "type": "start",
        "city": city,
        "cells": len(cells),
        "keywords": search_keywords,
        "total_steps": total_steps,
        "message": f"مسح {_city_ar(city)}: {len(cells)} منطقة × {len(search_keywords)} كلمة مفتاحية",
    })

    for kw_idx, kw in enumerate(search_keywords):
        for cell in cells:
            step += 1
            emit({
                "type": "progress",
                "step": step,
                "total_steps": total_steps,
                "keyword": kw,
                "cell_row": cell.row,
                "cell_col": cell.col,
                "lat": cell.lat,
                "lng": cell.lon,
                "raw_so_far": len(all_places),
                "message": f"منطقة {step}/{total_steps}: {kw} @ ({cell.lat:.3f}, {cell.lon:.3f})",
            })

            try:
                batch = await scrape_google_maps(
                    query=kw,
                    max_places=max_per_cell,
                    lang=lang,
                    headless=headless,
                    concurrency=concurrency,
                    lat=cell.lat,
                    lng=cell.lon,
                    zoom=zoom,
                )
                all_places.extend(batch)
                logger.info("Cell (%s,%s) keyword %r -> %d places (raw total %d)", cell.row, cell.col, kw, len(batch), len(all_places))
            except Exception as e:
                logger.warning("Cell scrape failed: %s", e)
                emit({
                    "type": "warning",
                    "step": step,
                    "message": f"فشلت المنطقة {step}: {e}",
                })

            if step < total_steps and pause_between_searches_sec > 0:
                await asyncio.sleep(pause_between_searches_sec)

    unique, dedupe_stats = deduplicate_places(all_places)

    result = {
        "type": "complete",
        "results": unique,
        "stats": {
            **dedupe_stats,
            "city": city,
            "cells_scanned": len(cells),
            "keywords": search_keywords,
            "total_steps": total_steps,
        },
        "message": (
            f"تم — {dedupe_stats['unique_count']} مكان فريد "
            f"({dedupe_stats['duplicates_removed']} مكرر أُزيل من {dedupe_stats['raw_count']} خام)"
        ),
    }
    emit(result)
    return result
