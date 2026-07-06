"""Deduplicate scraped Google Maps places."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def _normalize_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("966") and len(digits) > 9:
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits


def _normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _coord_key(place: Dict[str, Any]) -> str:
    coords = place.get("coordinates") or {}
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    if lat is None or lng is None:
        return ""
    return f"{round(float(lat), 4)},{round(float(lng), 4)}"


def _dedupe_key(place: Dict[str, Any]) -> Optional[str]:
    place_id = place.get("place_id")
    if place_id:
        return f"id:{place_id}"

    phone = _normalize_phone(place.get("phone"))
    if phone and len(phone) >= 8:
        return f"phone:{phone}"

    name = _normalize_name(place.get("name"))
    coord = _coord_key(place)
    if name and coord:
        return f"namecoord:{name}|{coord}"

    link = place.get("link") or ""
    if "/maps/place/" in link:
        return f"link:{link.split('?')[0]}"

    return None


def _richness_score(place: Dict[str, Any]) -> int:
    score = 0
    for field in ("phone", "website", "address", "rating", "place_id"):
        if place.get(field):
            score += 2
    if place.get("reviews_count"):
        score += 1
    if place.get("hours"):
        score += 1
    return score


def deduplicate_places(places: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Remove duplicates. Keeps the richest record when merging.
    Returns (unique_places, stats).
    """
    raw_count = len(places)
    by_key: Dict[str, Dict[str, Any]] = {}
    no_key: List[Dict[str, Any]] = []

    for place in places:
        key = _dedupe_key(place)
        if not key:
            no_key.append(place)
            continue
        existing = by_key.get(key)
        if existing is None or _richness_score(place) > _richness_score(existing):
            by_key[key] = place

    unique = list(by_key.values()) + no_key
    stats = {
        "raw_count": raw_count,
        "unique_count": len(unique),
        "duplicates_removed": raw_count - len(unique),
    }
    return unique, stats
