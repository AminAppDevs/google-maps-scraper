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
  gmaps_scraper_server scripts

caprover deploy -t deploy.tar.gz -a waleef-gmaps
```

---

## 4. App settings

| Setting | Value |
|---------|--------|
| **Container HTTP Port** | `80` |
| **Environment** | `GMAPS_DATA_DIR=/captain/data` (default in Dockerfile) |
| **Instance count** | `1` (scraping is heavy; avoid multiple instances on one DB) |
| **RAM** | **2 GB minimum** (Playwright + Chromium) |

Optional health check path: `/health`

---

## 5. Upload your existing local database (optional)

If you already scraped data locally and want it on CapRover:

```bash
# 1. Find the running container on your CapRover server (SSH)
docker ps | grep waleef-gmaps

# 2. Copy local DB into the persistent volume path inside the container
docker cp ./data/places.db <CONTAINER_ID>:/captain/data/places.db

# 3. Restart the app from CapRover dashboard
```

Replace `./data/places.db` with your local file path.

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
