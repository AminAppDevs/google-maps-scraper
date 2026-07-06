# Deploy to CapRover

Deploy **Waleef Maps Scraper** with Docker + persistent SQLite on CapRover.

## Files

| File | Purpose |
|------|---------|
| `captain-definition` | Tells CapRover to build from `Dockerfile` |
| `Dockerfile` | Playwright + FastAPI image |
| `scripts/docker-entrypoint.sh` | Creates data dir + runs DB migrations on start |

Database path inside the container: **`/captain/data/places.db`**  
Override with env var: **`GMAPS_DATA_DIR`**

**Seed database:** `seed/places.db` is bundled in the Docker image. On first start (or if DB is empty), it auto-copies **359 places** into `/captain/data/`. Redeploys with existing data do **not** overwrite your live DB.

To refresh the seed before deploy:
```bash
./scripts/copy-db-to-seed.sh
git add seed/places.db
git commit -m "Update seed database"
git push
```

---

## 1. Create the app in CapRover

1. CapRover dashboard → **Apps** → **Create New App**
2. Name example: `waleef-gmaps`
3. Enable **HTTPS** (Let’s Encrypt) if you want a domain

---

## 2. Persistent directory (required — keeps DB on restart)

1. Open your app → **App Configs** → **Persistent Directories**
2. Add:

   | Path in App | Label (optional) |
   |-------------|------------------|
   | `/captain/data` | `sqlite-db` |

3. Save & **Update** the app config

This maps `/captain/data` to a Docker volume on the host.  
**Restart** and **redeploy** keep the database. Only deleting the app *with* persistent data removes it.

---

## 3. Deploy

### Option A — Git push (recommended)

1. Push this repo to GitHub/GitLab
2. App → **Deployment** → **Method 3: Deploy via GitHub/Bitbucket/GitLab**
3. Connect repo + branch
4. CapRover detects `captain-definition` and builds automatically

### Option B — CLI tarball

From repo root:

```bash
tar -czf deploy.tar.gz \
  --exclude='.venv' \
  --exclude='data' \
  --exclude='output' \
  --exclude='.git' \
  captain-definition Dockerfile requirements.txt setup.py \
  seed/places.db gmaps_scraper_server scripts

caprover deploy -t deploy.tar.gz -a waleef-gmaps
```

---

## 4. App settings

| Setting | Value |
|---------|--------|
| **Container HTTP Port** | `80` |
| **Environment** | `GMAPS_DATA_DIR=/captain/data` (default in Dockerfile) |
| **GMAPS_SKIP_SEED** | `1` on production servers that already have data — blocks auto-seed on start and manual seed API (unless `force=true`) |
| **SEED_ADMIN_KEY** | Any secret string (e.g. `waleef-seed-2026`) — for importing DB without SSH |
| **Instance count** | `1` (scraping is heavy; avoid multiple instances on one DB) |
| **RAM** | **2 GB minimum** (Playwright + Chromium) |

Optional health check path: `/health`

---

## Safe redeploy (keep server DB, ship code only)

Use this when the server already has places + WhatsApp share status and you only want UI/code updates.

1. **CapRover → App Configs → Persistent Directories** — must include `/captain/data`
2. **Environment variables:**
   - `GMAPS_DATA_DIR=/captain/data`
   - `GMAPS_SKIP_SEED=1` ← prevents any seed copy on restart
3. **Do NOT** run `./scripts/copy-db-to-seed.sh` before deploy
4. Push code and rebuild:

```bash
git push origin main
# CapRover → Force rebuild
```

Or from repo root:

```bash
chmod +x scripts/deploy-safe.sh
./scripts/deploy-safe.sh
```

**What stays safe on redeploy**

| Item | Included in deploy? | Overwrites server DB? |
|------|---------------------|------------------------|
| `data/places.db` (local) | ❌ gitignored + .dockerignore | ❌ Never |
| `seed/places.db` (in image) | ✅ baked in image | ❌ Only if server DB is **empty** and `GMAPS_SKIP_SEED` is not set |
| `/captain/data/places.db` | ❌ persistent volume | ✅ **Kept** across redeploys |

**Never run** unless you intend to wipe server data:

```bash
curl -X POST ".../api/admin/seed-database?key=...&force=true"
docker cp ./seed/places.db <CONTAINER>:/captain/data/places.db
```

---

### A — Automatic (recommended)

1. Push repo **with** `seed/places.db` (see below)
2. CapRover → **Force rebuild** → wait for build
3. **Restart** the app

On start, if the DB is empty, logs show:
`Seeded database: 359 places copied...`

### B — Manual trigger from your Mac (no SSH)

1. CapRover → App → **App Configs** → **Environment Variables**
2. Add: `SEED_ADMIN_KEY` = `your-secret-here`
3. Save & restart
4. Redeploy must include `seed/places.db` in the Docker image (git push first)

From your Mac terminal:

```bash
# Check status
curl "https://YOUR-APP.yourdomain.com/api/admin/seed-status?key=your-secret-here"

# Import seed (empty DB)
curl -X POST "https://YOUR-APP.yourdomain.com/api/admin/seed-database?key=your-secret-here"

# Replace existing empty/wrong DB
curl -X POST "https://YOUR-APP.yourdomain.com/api/admin/seed-database?key=your-secret-here&force=true"
```

You should get JSON with `"count": 359`.

### Push seed to GitHub first

```bash
cd /Users/amin/Documents/waleef/gmaps-scraper-local
./scripts/copy-db-to-seed.sh   # refresh from local data/
git add seed/places.db
git commit -m "Add seed database (359 places)"
git push
```

Then CapRover **Force rebuild**.

---

## 6. Upload database via SSH (optional)

The image already includes `seed/places.db`. After redeploy + restart, empty servers auto-seed.

**Manual copy** (if you need to force-update without waiting for redeploy):

```bash
docker ps | grep waleef-gmaps
docker cp ./seed/places.db <CONTAINER_ID>:/captain/data/places.db
```

Then restart the app from CapRover.

---

## 6. How to make sure the DB is NOT deleted

| Action | DB safe? |
|--------|----------|
| App **restart** | ✅ Yes |
| **Redeploy** new version | ✅ Yes (if persistent dir is configured) |
| CapRover server **reboot** | ✅ Yes |
| **Delete app** without “delete persistent directories” | ⚠️ Volume may remain on disk but app is gone |
| **Delete app** + check **delete persistent data** | ❌ **DB deleted** |
| Rebuild container without persistent dir | ❌ **DB lost** on each deploy |

### Rules

1. **Always** configure `/captain/data` as a persistent directory before first real scrape.
2. When removing the app, **do not** tick “Also delete persistent directories” unless you intend to wipe data.
3. **Back up regularly** from the server:

```bash
docker ps | grep waleef-gmaps
docker cp <CONTAINER_ID>:/captain/data/places.db ./places-backup-$(date +%F).db
```

4. Run **one instance only** — multiple containers sharing one SQLite file can corrupt it.

---

## 7. Verify after deploy

1. Open `https://waleef-gmaps.yourdomain.com`
2. Check health: `https://waleef-gmaps.yourdomain.com/health`
3. Run a small scrape → **النتائج** tab should show data
4. Restart app from CapRover → data should still be there

---

## Troubleshooting

**Scrape fails / browser error**  
Increase app memory to 2–4 GB.

**Empty results after redeploy**  
Persistent directory was not set before first deploy. Upload backup DB (step 5) or scrape again.

**502 on CapRover**  
Confirm container port is **80** and app logs show `Uvicorn running`.
