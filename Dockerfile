# Playwright base includes Chromium + system deps for headless scraping.
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GMAPS_DATA_DIR=/captain/data \
    PORT=80

COPY requirements.txt setup.py ./
COPY gmaps_scraper_server ./gmaps_scraper_server

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e . --no-deps

COPY seed/places.db /app/seed/places.db
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["sh", "-c", "uvicorn gmaps_scraper_server.main_api:app --host 0.0.0.0 --port ${PORT}"]
