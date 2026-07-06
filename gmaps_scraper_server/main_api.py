from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncIterator
import json
import logging
import asyncio
import os

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from gmaps_scraper_server.scraper import scrape_google_maps
    from gmaps_scraper_server.city_scraper import scrape_city_grid
    from gmaps_scraper_server.dedupe import deduplicate_places
    from gmaps_scraper_server.grid import SAUDI_CITIES, estimate_grid_count
    from gmaps_scraper_server.database import (
        init_db,
        upsert_places,
        list_places,
        get_place,
        update_place,
        delete_place,
        cleanup_invalid_places,
        seed_from_bundle,
        mark_whatsapp_shared,
        unmark_whatsapp_shared,
        get_stats,
    )
    from gmaps_scraper_server.whatsapp import whatsapp_url, whatsapp_link_parts, whatsapp_desktop_url, build_waleef_message
except ImportError:
    logging.error("Could not import scraper modules")

    def scrape_google_maps(*args, **kwargs):
        raise ImportError("Scraper function not available.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Google Maps Scraper",
    description="Local Google Maps scraper with SQLite + WhatsApp outreach.",
    version="0.4.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


class ScrapeRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_places: Optional[int] = Field(None, ge=1, le=120)
    lang: str = "en"
    headless: bool = True
    concurrency: int = Field(5, ge=1, le=20)
    dedupe: bool = True
    save_to_db: bool = True


class CityScrapeRequest(BaseModel):
    city: str = Field(..., min_length=1)
    keyword: Optional[str] = Field(None)
    lang: str = "en"
    zoom: int = Field(15, ge=12, le=17)
    cell_size_km: float = Field(4.0, ge=1.5, le=8.0)
    max_per_cell: int = Field(120, ge=1, le=120)
    headless: bool = True
    concurrency: int = Field(5, ge=1, le=10)
    include_vet_clinics: bool = True
    save_to_db: bool = True


class SavePlacesRequest(BaseModel):
    places: List[Dict[str, Any]]
    source_label: str = ""
    city: str = ""


class UpdatePlaceRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    whatsapp_shared: Optional[bool] = None


async def _run_scrape(
    query: str,
    max_places: Optional[int],
    lang: str,
    headless: bool,
    concurrency: int,
    dedupe: bool = True,
) -> Dict[str, Any]:
    results = await asyncio.wait_for(
        scrape_google_maps(
            query=query,
            max_places=max_places,
            lang=lang,
            headless=headless,
            concurrency=concurrency,
        ),
        timeout=300,
    )
    stats = {"raw_count": len(results), "unique_count": len(results), "duplicates_removed": 0}
    if dedupe and results:
        results, stats = deduplicate_places(results)
    from gmaps_scraper_server.validation import filter_places_for_saudi
    results, filter_stats = filter_places_for_saudi(results)
    stats = {**stats, **filter_stats}
    return {"results": results, "stats": stats}


def _save_results(results: List[Dict[str, Any]], source_label: str, city: str) -> Dict[str, int]:
    if not results:
        return {"inserted": 0, "updated": 0, "total_unique": 0}
    return upsert_places(results, source_label=source_label, city=city)


@app.get("/")
async def read_root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/cities")
async def api_list_cities():
    return {
        "cities": [
            {"name": name, "estimated_zones": estimate_grid_count(name, 3.0)}
            for name in sorted(SAUDI_CITIES.keys())
        ]
    }


def _enrich_place(p: Dict[str, Any]) -> Dict[str, Any]:
    parts = whatsapp_link_parts(p.get("phone"), p.get("name", ""))
    if parts:
        p["whatsapp_phone"] = parts["phone"]
        p["whatsapp_message"] = parts["message"]
        p["whatsapp_url"] = whatsapp_url(p.get("phone"), p.get("name", ""))
        p["whatsapp_desktop_url"] = whatsapp_desktop_url(p.get("phone"), p.get("name", ""))
    else:
        p["whatsapp_phone"] = None
        p["whatsapp_message"] = None
        p["whatsapp_url"] = None
        p["whatsapp_desktop_url"] = None
    return p


@app.get("/api/places")
async def api_list_places(
    shared: Optional[bool] = Query(None),
    city: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    all_rows: bool = Query(False, description="Return all rows (for export)"),
):
    if all_rows:
        result = list_places(shared=shared, city=city, search=search, page=1, page_size=100000)
    else:
        result = list_places(shared=shared, city=city, search=search, page=page, page_size=page_size)

    places = [_enrich_place(p) for p in result["places"]]
    return {
        "places": places,
        "pagination": result["pagination"],
        "stats": get_stats(),
    }


@app.get("/api/places/stats")
async def api_places_stats():
    return get_stats()


@app.post("/api/places/save")
async def api_save_places(body: SavePlacesRequest):
    save_stats = _save_results(body.places, body.source_label, body.city)
    return {"save_stats": save_stats, "stats": get_stats()}


@app.get("/api/places/{place_id}")
async def api_get_place(place_id: int):
    row = get_place(place_id)
    if not row:
        raise HTTPException(status_code=404, detail="Place not found")
    return _enrich_place(row)


@app.patch("/api/places/{place_id}")
async def api_update_place(place_id: int, body: UpdatePlaceRequest):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = update_place(place_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Place not found")
    return {"place": _enrich_place(row), "stats": get_stats()}


@app.delete("/api/places/{place_id}")
async def api_delete_place(place_id: int):
    if not delete_place(place_id):
        raise HTTPException(status_code=404, detail="Place not found")
    return {"ok": True, "stats": get_stats()}


def _check_seed_admin(key: Optional[str]) -> None:
    expected = os.environ.get("SEED_ADMIN_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Set SEED_ADMIN_KEY in CapRover env vars first, then call this endpoint",
        )
    if not key or key != expected:
        raise HTTPException(status_code=403, detail="Invalid seed key")


@app.get("/api/admin/seed-status")
async def api_seed_status(key: Optional[str] = Query(None)):
    """Check DB count and whether seed file exists in the container."""
    _check_seed_admin(key)
    from gmaps_scraper_server.database import SEED_PATH, DB_PATH, _place_count

    return {
        "db_path": str(DB_PATH),
        "seed_path": str(SEED_PATH),
        "seed_exists": SEED_PATH.is_file(),
        "place_count": _place_count(),
        "stats": get_stats(),
    }


@app.post("/api/admin/seed-database")
async def api_seed_database(
    force: bool = Query(False),
    key: Optional[str] = Query(None),
    x_seed_key: Optional[str] = Header(None, alias="X-Seed-Key"),
):
    """Import bundled seed/places.db — no SSH required."""
    _check_seed_admin(key or x_seed_key)
    result = seed_from_bundle(force=force)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Seed failed"))
    result["stats"] = get_stats()
    return result


@app.post("/api/places/cleanup-invalid")
async def api_cleanup_invalid_places():
    result = cleanup_invalid_places()
    return {"ok": True, **result, "stats": get_stats()}


@app.post("/api/places/{place_id}/whatsapp-shared")
async def api_mark_whatsapp_shared(place_id: int):
    row = mark_whatsapp_shared(place_id)
    if not row:
        raise HTTPException(status_code=404, detail="Place not found")
    return _enrich_place(row)


@app.delete("/api/places/{place_id}/whatsapp-shared")
async def api_unmark_whatsapp_shared(place_id: int):
    row = unmark_whatsapp_shared(place_id)
    if not row:
        raise HTTPException(status_code=404, detail="Place not found")
    return row


@app.get("/api/whatsapp/preview")
async def api_whatsapp_preview(name: str = Query("متجر")):
    return {"message": build_waleef_message(name)}


@app.post("/api/scrape")
async def run_scrape_api(body: ScrapeRequest):
    logging.info("UI scrape: query=%r max_places=%s lang=%s", body.query, body.max_places, body.lang)
    try:
        payload = await _run_scrape(
            query=body.query,
            max_places=body.max_places,
            lang=body.lang,
            headless=body.headless,
            concurrency=body.concurrency,
            dedupe=body.dedupe,
        )
        results = payload["results"]
        save_stats = {}
        if body.save_to_db and results:
            save_stats = _save_results(results, source_label=body.query, city="")
            payload["save_stats"] = save_stats
        logging.info("Scraping finished for %r — %d unique", body.query, len(results))
        return payload
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scraping timed out after 5 minutes")
    except ImportError:
        raise HTTPException(status_code=500, detail="Scraper not available. Run ./scripts/setup.sh")
    except Exception as e:
        logging.error("Scrape error for %r: %s", body.query, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scrape-city/stream")
async def run_scrape_city_stream(body: CityScrapeRequest):
    if body.city not in SAUDI_CITIES:
        raise HTTPException(status_code=400, detail=f"Unknown city. Choose from: {', '.join(SAUDI_CITIES)}")

    queue: asyncio.Queue = asyncio.Queue()
    save_to_db = body.save_to_db
    city_name = body.city

    def on_progress(event: Dict[str, Any]) -> None:
        if event.get("type") == "complete" and save_to_db and event.get("results"):
            save_stats = _save_results(
                event["results"],
                source_label=f"city-scan:{city_name}",
                city=city_name,
            )
            event["save_stats"] = save_stats
        queue.put_nowait(event)

    async def run_job() -> None:
        try:
            await scrape_city_grid(
                city=body.city,
                keyword=body.keyword,
                lang=body.lang,
                zoom=body.zoom,
                cell_size_km=body.cell_size_km,
                max_per_cell=body.max_per_cell,
                headless=body.headless,
                concurrency=body.concurrency,
                include_vet_clinics=body.include_vet_clinics,
                on_progress=on_progress,
            )
        except Exception as e:
            await queue.put({"type": "error", "message": str(e)})
        finally:
            await queue.put(None)

    async def event_generator() -> AsyncIterator[str]:
        task = asyncio.create_task(run_job())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + "\n"
        finally:
            await task

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@app.post("/scrape", response_model=List[Dict[str, Any]])
async def run_scrape(
    query: str = Query(...),
    max_places: Optional[int] = Query(None),
    lang: str = Query("en"),
    headless: bool = Query(True),
    concurrency: int = Query(5),
):
    try:
        payload = await _run_scrape(query, max_places, lang, headless, concurrency)
        return payload["results"]
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scraping timed out after 5 minutes")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scrape-get", response_model=List[Dict[str, Any]])
async def run_scrape_get(
    query: str = Query(...),
    max_places: Optional[int] = Query(None),
    lang: str = Query("en"),
    headless: bool = Query(True),
    concurrency: int = Query(5),
):
    try:
        payload = await _run_scrape(query, max_places, lang, headless, concurrency)
        return payload["results"]
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scraping timed out after 5 minutes")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "db": get_stats()}
