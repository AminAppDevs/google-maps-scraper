"""Validate and clean scraped places for Saudi Arabia outreach."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .grid import SAUDI_CITIES, bbox_from_tuple

# Full KSA approximate bounds
SAUDI_BBOX = (16.0, 34.5, 32.5, 55.7)

# Known US/global chains that pollute geo searches (not real KSA listings)
US_CHAIN_NAMES = re.compile(
    r"\b(petsmart|petco|pet\s*supermarket|chewy|pet\s*land\s*usa)\b",
    re.IGNORECASE,
)

BAD_ADDRESS_RE = re.compile(
    r"(ساعات\s*العمل|الاطّلاع|الاطلاع|نسخ\s*ساعات|View more hours|open hours|"
    r"show open hours|copy\s*hours|^\d+\s*[صم]\s*[·\.]|"
    r"^[\d\s،·\.]+(?:المملكة|$))",
    re.IGNORECASE,
)

SAUDI_ADDRESS_HINT = re.compile(
    r"(المملكة\s*العربية\s*السعودية|السعودية|"
    r"الرياض|جدة|الدمام|الخبر|الظهران|الاحساء|الأحساء|مكة|المدينة|"
    r"تبوك|أبها|خميس|نجران|جازان|الطائف|بريدة|القصيم|"
    r"Riyadh|Jeddah|Dammam|Khobar|Saudi)",
    re.IGNORECASE,
)

# Must match name or Google category
PET_KEYWORDS = re.compile(
    r"(?:"
    r"pet\s*shop|pet\s*store|petshop|pets?|paw|"
    r"بتس|پتس|"
    r"veterinar|vet\s*clinic|"
    r"حيوان(?:ات)?|أليف|اليف|اليفه|اليفة|"
    r"بيطر|بيطري|بيطرية|"
    r"طيور|طير|أسماك|اسماك|زينة|"
    r"كلاب|كلب|قطة|قطط|كات\b|"
    r"dog|cat|bird|fish|aquarium|kennel|"
    r"بيرد|"
    r"صقور|صقر|"
    r"groom|تجميل\s*حيوان|"
    r"مستلزمات\s*حيوان|متجر\s*حيوان|"
    r"animals?|zoo|"
    r"كائنات|"
    r"حياة\s*مائ|مائ(?:ي|ی)(?:ه|ة)?|aquatic"
    r")",
    re.IGNORECASE,
)

# Always exclude — supermarkets, IKEA, pharmacies, etc.
NON_PET_HARD_EXCLUDE = re.compile(
    r"(?:"
    r"ikea|إيكيا|"
    r"tamimi|التميمي|"
    r"nahdi|النهدي|"
    r"carrefour|كارفور|"
    r"panda\s*market|بنده|"
    r"danube|دانوب|"
    r"farm\s*superstore|اسواق\s*المزرعة|"
    r"hypermarket|supermarket|سوبر\s*ماركت|"
    r"pharmacy|صيدل|"
    r"hardware|مواد\s*بناء|"
    r"arcade|أركيد|"
    r"advertis|دعاية|إعلان|"
    r"restaurant|مطع|"
    r"hotel|فندق|"
    r"bank|بنك|"
    r"mosque|مسجد|"
    r"grocery|بقالة|"
    r"العثيم|othaim|"
    r"أسواق\s*التميمي|أسواق\s*المزرعة|أسواق\s*المنتزه|أسواق\s*زاد|"
    r"أسواق\s*النهدي|أسواق\s*عبدالله|أسواق\s*النخبة|أسواق\s*مكان|"
    r"كماليات|"
    r"مواشي|"
    r"building\s*materials"
    r")",
    re.IGNORECASE,
)


def _digits(phone: Optional[str]) -> str:
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def normalize_saudi_phone(phone: Optional[str]) -> Optional[str]:
    """Return 966XXXXXXXXX for valid Saudi mobile/landline, else None."""
    digits = _digits(phone)
    if not digits:
        return None

    if digits.startswith("966"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits

    # Saudi mobile: 5XXXXXXXX (9 digits)
    if len(national) == 9 and national[0] == "5":
        return "966" + national
    # Landline with area code (9–10 digits, not US)
    if len(national) in (9, 10) and national[0] in "0123456789" and not national.startswith("5"):
        if len(national) == 10 and national[0] == "1":
            return None  # US-looking
        return "966" + national[-9:] if len(national) > 9 else "966" + national

    return None


def is_us_or_foreign_phone(phone: Optional[str]) -> bool:
    digits = _digits(phone)
    if not digits:
        return False
    if digits.startswith("966"):
        return False
    # US/Canada +1XXXXXXXXXX
    if digits.startswith("1") and len(digits) == 11:
        return True
    # 10-digit US number (area codes don't start with 5 for mobile pattern we use)
    if len(digits) == 10 and not digits.startswith("05"):
        return True
    if len(digits) == 11 and digits[0] != "9":
        return True
    return False


def is_in_saudi(lat: float, lng: float) -> bool:
    min_lat, min_lon, max_lat, max_lon = SAUDI_BBOX
    return min_lat <= lat <= max_lat and min_lon <= lng <= max_lon


def is_in_city_bbox(lat: float, lng: float, city: str, padding_deg: float = 0.12) -> bool:
    if city not in SAUDI_CITIES:
        return is_in_saudi(lat, lng)
    bbox = bbox_from_tuple(SAUDI_CITIES[city])
    return (
        bbox.min_lat - padding_deg <= lat <= bbox.max_lat + padding_deg
        and bbox.min_lon - padding_deg <= lng <= bbox.max_lon + padding_deg
    )


def is_valid_address(address: Optional[str]) -> bool:
    if not address:
        return False
    text = address.strip()
    if len(text) < 8:
        return False
    if BAD_ADDRESS_RE.search(text):
        return False
    # Must have letters (not just numbers/punctuation)
    if not re.search(r"[\u0600-\u06FFa-zA-Z]", text):
        return False
    return True


def clean_address(address: Optional[str]) -> Optional[str]:
    if not address or not is_valid_address(address):
        return None
    text = re.sub(r"\s+", " ", address.strip())
    return text


def _coords(place: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    coords = place.get("coordinates") or {}
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    try:
        return (float(lat), float(lng)) if lat is not None and lng is not None else (None, None)
    except (TypeError, ValueError):
        return None, None


def _place_search_text(place: Dict[str, Any]) -> str:
    name = place.get("name") or ""
    cats = place.get("categories")
    if isinstance(cats, list):
        cat_text = " ".join(str(c) for c in cats)
    elif cats:
        cat_text = str(cats)
    else:
        cat_text = ""
    return f"{name} {cat_text}".strip()


def is_pet_related(place: Dict[str, Any]) -> bool:
    """True if name/categories indicate pet store, vet, or pet supplies."""
    text = _place_search_text(place)
    if not text:
        return False
    if NON_PET_HARD_EXCLUDE.search(text):
        return False
    return bool(PET_KEYWORDS.search(text))


def should_reject_non_pet(place: Dict[str, Any]) -> bool:
    return not is_pet_related(place)


def should_reject_place(place: Dict[str, Any], city: Optional[str] = None) -> bool:
    """Drop listings that are clearly not in Saudi Arabia."""
    phone = place.get("phone")
    lat, lng = _coords(place)
    name = place.get("name") or ""

    if phone and is_us_or_foreign_phone(phone):
        return True

    if lat is not None and lng is not None:
        if city:
            if not is_in_city_bbox(lat, lng, city):
                return True
        elif not is_in_saudi(lat, lng):
            return True

    if lat is None and lng is None:
        saudi_phone = normalize_saudi_phone(phone)
        addr = place.get("address") or ""
        if US_CHAIN_NAMES.search(name) and not saudi_phone and not SAUDI_ADDRESS_HINT.search(addr):
            return True

    return False


def clean_place_record(place: Dict[str, Any], city: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Normalize phone/address/email and drop invalid KSA listings.
    Returns None if the place should be discarded.
    """
    if should_reject_place(place, city=city):
        return None

    cleaned = dict(place)

    phone = cleaned.get("phone")
    if phone:
        saudi = normalize_saudi_phone(phone)
        cleaned["phone"] = saudi  # None if not valid Saudi

    cleaned["address"] = clean_address(cleaned.get("address"))

    email = cleaned.get("email")
    if email:
        email = email.strip().lower()
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            cleaned["email"] = None
        else:
            cleaned["email"] = email

    # Must have a valid Saudi phone to save or keep
    if not cleaned.get("phone"):
        return None

    if should_reject_non_pet(cleaned):
        return None

    return cleaned


def filter_places_for_saudi(
    places: List[Dict[str, Any]],
    city: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Filter and clean places. Returns (kept, stats)."""
    raw = len(places)
    kept: List[Dict[str, Any]] = []
    rejected_foreign = 0
    rejected_no_phone = 0
    rejected_non_pet = 0

    for place in places:
        cleaned = clean_place_record(place, city=city)
        if cleaned is None:
            if should_reject_place(place, city=city):
                rejected_foreign += 1
            elif not normalize_saudi_phone(place.get("phone")):
                rejected_no_phone += 1
            elif should_reject_non_pet(place):
                rejected_non_pet += 1
            else:
                rejected_no_phone += 1
            continue
        kept.append(cleaned)

    return kept, {
        "raw_count": raw,
        "kept_count": len(kept),
        "rejected_foreign": rejected_foreign,
        "rejected_no_phone": rejected_no_phone,
        "rejected_non_pet": rejected_non_pet,
        "filtered_out": raw - len(kept),
    }
