# Google Maps Scraper — local setup

## Quick start

```bash
cd /Users/amin/Documents/waleef/gmaps-scraper-local
./start.sh
```

Open **http://localhost:8001**

## Modes

### Single search
One query, auto-scroll, dedupe — up to ~120 results.

### Full city scan
- Splits city into a **grid of zones**
- **Auto-zooms** into each zone (zoom 15)
- **Deep scrolls** the results list per zone
- Runs **pet store + vet clinic** keywords (optional)
- **Removes duplicates** by place_id / phone / name+location
- Shows live progress bar

**Dammam** (~4 km zones): ~56 zones × 2 keywords ≈ **1–2 hours**  
**Riyadh**: use **5–6 km** zone size or expect several hours

## Export

Download cleaned **CSV** or **JSON** when done.
