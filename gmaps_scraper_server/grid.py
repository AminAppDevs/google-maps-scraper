"""Geographic grid utilities for city-wide Google Maps scraping."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

KM_PER_DEG_LAT = 111.0


@dataclass(frozen=True)
class Cell:
    lat: float
    lon: float
    row: int
    col: int


@dataclass(frozen=True)
class BoundingBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


# Saudi city bounding boxes (approximate)
SAUDI_CITIES: Dict[str, Tuple[float, float, float, float]] = {
    "Riyadh": (24.45, 46.45, 25.05, 47.05),
    "Jeddah": (21.40, 39.05, 21.75, 39.35),
    "Dammam": (26.25, 49.95, 26.55, 50.25),
    "Khobar": (26.20, 50.05, 26.35, 50.25),
    "Mecca": (21.35, 39.75, 21.50, 39.95),
    "Medina": (24.40, 39.50, 24.55, 39.70),
    "Abha": (18.15, 42.45, 18.30, 42.65),
    "Tabuk": (28.35, 36.45, 28.50, 36.65),
}


def bbox_from_tuple(t: Tuple[float, float, float, float]) -> BoundingBox:
    return BoundingBox(min_lat=t[0], min_lon=t[1], max_lat=t[2], max_lon=t[3])


def _lon_step_km(bbox: BoundingBox, cell_size_km: float) -> float:
    mid_lat = (bbox.min_lat + bbox.max_lat) / 2
    km_per_deg_lon = KM_PER_DEG_LAT * math.cos(math.radians(mid_lat))
    if km_per_deg_lon <= 0:
        km_per_deg_lon = KM_PER_DEG_LAT
    return cell_size_km / km_per_deg_lon


def generate_grid(bbox: BoundingBox, cell_size_km: float = 3.0) -> List[Cell]:
    """Divide bbox into ~cell_size_km squares; return center of each cell."""
    cell_size_km = max(cell_size_km, 1.0)
    lat_step = cell_size_km / KM_PER_DEG_LAT
    lon_step = _lon_step_km(bbox, cell_size_km)

    cells: List[Cell] = []
    row = 0
    lat = bbox.min_lat + lat_step / 2
    while lat < bbox.max_lat:
        col = 0
        lon = bbox.min_lon + lon_step / 2
        while lon < bbox.max_lon:
            cells.append(Cell(lat=lat, lon=lon, row=row, col=col))
            lon += lon_step
            col += 1
        lat += lat_step
        row += 1
    return cells


def estimate_grid_count(city: str, cell_size_km: float = 3.0) -> int:
    if city not in SAUDI_CITIES:
        return 0
    return len(generate_grid(bbox_from_tuple(SAUDI_CITIES[city]), cell_size_km))
