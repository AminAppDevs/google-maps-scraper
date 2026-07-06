"""SQLite persistence for scraped places."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .dedupe import _normalize_phone, deduplicate_places

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("GMAPS_DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "places.db"
RIYADH_TZ = ZoneInfo("Asia/Riyadh")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                place_id TEXT,
                name TEXT NOT NULL,
                phone TEXT,
                address TEXT,
                rating REAL,
                reviews_count INTEGER,
                website TEXT,
                link TEXT,
                latitude REAL,
                longitude REAL,
                categories TEXT,
                hours TEXT,
                source_label TEXT,
                city TEXT,
                whatsapp_shared INTEGER NOT NULL DEFAULT 0,
                whatsapp_shared_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_places_place_id ON places(place_id);
            CREATE INDEX IF NOT EXISTS idx_places_phone ON places(phone);
            CREATE INDEX IF NOT EXISTS idx_places_shared ON places(whatsapp_shared);
            CREATE INDEX IF NOT EXISTS idx_places_shared_at ON places(whatsapp_shared_at);
            CREATE INDEX IF NOT EXISTS idx_places_created_at ON places(created_at);
            CREATE INDEX IF NOT EXISTS idx_places_name ON places(name);
            """
        )
        _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(places)").fetchall()}
    if "email" not in cols:
        conn.execute("ALTER TABLE places ADD COLUMN email TEXT")
        conn.commit()


def _place_to_row(place: Dict[str, Any], source_label: str = "", city: str = "") -> Dict[str, Any]:
    coords = place.get("coordinates") or {}
    categories = place.get("categories")
    hours = place.get("hours")
    return {
        "place_id": place.get("place_id") or None,
        "name": place.get("name") or "Unknown",
        "phone": place.get("phone") or None,
        "email": place.get("email") or None,
        "address": place.get("address") or None,
        "rating": place.get("rating"),
        "reviews_count": place.get("reviews_count"),
        "website": place.get("website") or None,
        "link": place.get("link") or None,
        "latitude": coords.get("latitude"),
        "longitude": coords.get("longitude"),
        "categories": json.dumps(categories, ensure_ascii=False) if isinstance(categories, list) else (categories or None),
        "hours": json.dumps(hours, ensure_ascii=False) if isinstance(hours, list) else (hours or None),
        "source_label": source_label or None,
        "city": city or None,
    }


def _find_existing_id(conn: sqlite3.Connection, place_id: Optional[str], phone: Optional[str]) -> Optional[int]:
    if place_id:
        row = conn.execute("SELECT id FROM places WHERE place_id = ?", (place_id,)).fetchone()
        if row:
            return row["id"]
    norm = _normalize_phone(phone)
    if norm and len(norm) >= 8:
        rows = conn.execute("SELECT id, phone FROM places WHERE phone IS NOT NULL").fetchall()
        for row in rows:
            if _normalize_phone(row["phone"]) == norm:
                return row["id"]
    return None


def upsert_places(
    places: List[Dict[str, Any]],
    source_label: str = "",
    city: str = "",
) -> Dict[str, int]:
    """Insert or update places. Skips entries without a valid Saudi phone."""
    from .validation import normalize_saudi_phone

    unique, _ = deduplicate_places(places)
    now = _now_iso()
    inserted = 0
    updated = 0
    skipped_no_phone = 0

    with get_connection() as conn:
        for place in unique:
            phone = normalize_saudi_phone(place.get("phone"))
            if not phone:
                skipped_no_phone += 1
                continue
            place = {**place, "phone": phone}

            row = _place_to_row(place, source_label, city)
            existing_id = _find_existing_id(conn, row["place_id"], row["phone"])

            if existing_id:
                conn.execute(
                    """
                    UPDATE places SET
                        place_id = COALESCE(?, place_id),
                        name = ?, phone = COALESCE(?, phone),
                        email = COALESCE(?, email),
                        address = COALESCE(?, address),
                        rating = COALESCE(?, rating),
                        reviews_count = COALESCE(?, reviews_count),
                        website = COALESCE(?, website),
                        link = COALESCE(?, link),
                        latitude = COALESCE(?, latitude),
                        longitude = COALESCE(?, longitude),
                        categories = COALESCE(?, categories),
                        hours = COALESCE(?, hours),
                        source_label = COALESCE(?, source_label),
                        city = COALESCE(?, city),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        row["place_id"], row["name"], row["phone"], row["email"],
                        row["address"], row["rating"], row["reviews_count"],
                        row["website"], row["link"], row["latitude"], row["longitude"],
                        row["categories"], row["hours"], row["source_label"], row["city"],
                        now, existing_id,
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO places (
                        place_id, name, phone, email, address, rating, reviews_count,
                        website, link, latitude, longitude, categories, hours,
                        source_label, city, whatsapp_shared, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        row["place_id"], row["name"], row["phone"], row["email"], row["address"],
                        row["rating"], row["reviews_count"], row["website"], row["link"],
                        row["latitude"], row["longitude"], row["categories"], row["hours"],
                        row["source_label"], row["city"], now, now,
                    ),
                )
                inserted += 1
        conn.commit()

    return {
        "inserted": inserted,
        "updated": updated,
        "total_unique": len(unique),
        "skipped_no_phone": skipped_no_phone,
    }


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["whatsapp_shared"] = bool(d.get("whatsapp_shared"))
    if d.get("categories"):
        try:
            parsed = json.loads(d["categories"])
            d["categories"] = parsed if isinstance(parsed, list) else d["categories"]
        except json.JSONDecodeError:
            pass
    if d.get("hours"):
        try:
            parsed = json.loads(d["hours"])
            d["hours"] = parsed if isinstance(parsed, list) else d["hours"]
        except json.JSONDecodeError:
            pass
    return d


def list_places(
    shared: Optional[bool] = None,
    city: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> Dict[str, Any]:
    clauses = ["1=1"]
    params: List[Any] = []

    if shared is not None:
        clauses.append("whatsapp_shared = ?")
        params.append(1 if shared else 0)
    if city:
        clauses.append("city = ?")
        params.append(city)
    if search:
        clauses.append("(name LIKE ? OR phone LIKE ? OR address LIKE ?)")
        q = f"%{search}%"
        params.extend([q, q, q])

    where = " AND ".join(clauses)
    order = (
        "whatsapp_shared ASC, "
        "CASE WHEN phone IS NOT NULL AND phone != '' THEN 0 ELSE 1 END, "
        "name ASC"
    )

    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM places WHERE {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM places WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return {
        "places": [_row_to_dict(r) for r in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


def mark_whatsapp_shared(place_id: int) -> Optional[Dict[str, Any]]:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE places SET whatsapp_shared = 1, whatsapp_shared_at = ?, updated_at = ? WHERE id = ?",
            (now, now, place_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
    return _row_to_dict(row) if row else None


def unmark_whatsapp_shared(place_id: int) -> Optional[Dict[str, Any]]:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE places SET whatsapp_shared = 0, whatsapp_shared_at = NULL, updated_at = ? WHERE id = ?",
            (now, place_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_place(place_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_place(place_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {"name", "phone", "email", "address", "city", "whatsapp_shared"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_place(place_id)

    now = _now_iso()
    if "whatsapp_shared" in updates:
        shared = bool(updates["whatsapp_shared"])
        updates["whatsapp_shared"] = 1 if shared else 0
        updates["whatsapp_shared_at"] = now if shared else None

    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [place_id]

    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE places SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete_place(place_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM places WHERE id = ?", (place_id,))
        conn.commit()
        return cur.rowcount > 0


def cleanup_invalid_places() -> Dict[str, int]:
    """Remove foreign/invalid listings and any row without a valid Saudi phone."""
    from .validation import clean_address, is_us_or_foreign_phone, normalize_saudi_phone, should_reject_place

    deleted = 0
    deleted_no_phone = 0
    phone_fixed = 0

    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM places").fetchall()
        for row in rows:
            p = _row_to_dict(row)
            p["coordinates"] = {"latitude": p.get("latitude"), "longitude": p.get("longitude")}

            if should_reject_place(p, city=p.get("city")):
                conn.execute("DELETE FROM places WHERE id = ?", (p["id"],))
                deleted += 1
                continue

            phone = p.get("phone")
            saudi = normalize_saudi_phone(phone) if phone else None

            if not saudi:
                conn.execute("DELETE FROM places WHERE id = ?", (p["id"],))
                deleted_no_phone += 1
                continue

            if phone and is_us_or_foreign_phone(phone):
                conn.execute("DELETE FROM places WHERE id = ?", (p["id"],))
                deleted_no_phone += 1
                continue

            addr = clean_address(p.get("address"))
            updates = {}
            if saudi != phone:
                updates["phone"] = saudi
            if addr != p.get("address"):
                updates["address"] = addr
            if updates:
                updates["updated_at"] = _now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE places SET {set_clause} WHERE id = ?",
                    list(updates.values()) + [p["id"]],
                )
                phone_fixed += 1

        cur = conn.execute("DELETE FROM places WHERE phone IS NULL OR phone = ''")
        deleted_no_phone += cur.rowcount
        conn.commit()

    return {
        "deleted": deleted,
        "deleted_no_phone": deleted_no_phone,
        "fixed": phone_fixed,
    }


def _period_starts_utc() -> Dict[str, Optional[str]]:
    """Calendar period starts in Asia/Riyadh, returned as UTC ISO strings."""
    now_local = datetime.now(RIYADH_TZ)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_sunday = (now_local.weekday() + 1) % 7
    week = today - timedelta(days=days_since_sunday)
    month = today.replace(day=1)
    year = today.replace(month=1, day=1)

    def to_iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    return {
        "today": to_iso(today),
        "week": to_iso(week),
        "month": to_iso(month),
        "year": to_iso(year),
        "all": None,
    }


def _count_collected_since(conn: sqlite3.Connection, since: Optional[str]) -> int:
    if since is None:
        return conn.execute("SELECT COUNT(*) AS c FROM places").fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) AS c FROM places WHERE created_at >= ?",
        (since,),
    ).fetchone()["c"]


def _count_shared_since(conn: sqlite3.Connection, since: Optional[str]) -> int:
    if since is None:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM places WHERE whatsapp_shared = 1"
        ).fetchone()["c"]
    return conn.execute(
        """
        SELECT COUNT(*) AS c FROM places
        WHERE whatsapp_shared = 1
          AND whatsapp_shared_at IS NOT NULL
          AND whatsapp_shared_at >= ?
        """,
        (since,),
    ).fetchone()["c"]


def get_stats() -> Dict[str, Any]:
    periods = _period_starts_utc()
    collected: Dict[str, int] = {}
    shared: Dict[str, int] = {}

    with get_connection() as conn:
        for key, since in periods.items():
            collected[key] = _count_collected_since(conn, since)
            shared[key] = _count_shared_since(conn, since)

        total = collected["all"]
        shared_all = shared["all"]
        with_phone = conn.execute(
            "SELECT COUNT(*) AS c FROM places WHERE phone IS NOT NULL AND phone != ''"
        ).fetchone()["c"]

    return {
        "total": total,
        "whatsapp_shared": shared_all,
        "whatsapp_pending": total - shared_all,
        "with_phone": with_phone,
        "collected": collected,
        "shared": shared,
    }
