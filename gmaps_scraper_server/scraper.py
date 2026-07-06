import json
import asyncio
import re
import random
import logging
import os
from typing import Callable, Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urlencode

# Import the extraction functions from our helper module
from . import extractor
from .job_manager import ScrapeCancelled

# --- Logging Configuration ---
logger = logging.getLogger(__name__)

# --- Constants ---
BASE_URL = "https://www.google.com/maps/search/"
DEFAULT_TIMEOUT = 30000  # 30 seconds for navigation and selectors
SCROLL_PAUSE_TIME = 2.0  # Pause between scrolls
MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS = 12  # Stop scrolling if no new links found after this many scrolls

# User agent rotation for anti-detection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def random_delay(min_sec=1.0, max_sec=2.0):
    """Returns random delay for anti-detection"""
    return random.uniform(min_sec, max_sec)


CONSENT_SELECTORS = [
    "#L2AGLb",
    "button[jsname='b3VHJd']",
    "button[aria-label='Alle akzeptieren']",
    "button[aria-label='Accept all']",
    "button[aria-label='I agree']",
    "button[aria-label='Aceptar todo']",
    "button[aria-label='Tout accepter']",
    "button[aria-label='Accetta tutto']",
    "button[aria-label='قبول الكل']",
    "button[aria-label='أوافق']",
    "button[aria-label='موافق']",
    "button[aria-label='الموافقة على الكل']",
]

CONSENT_BUTTON_NAMES = [
    "Accept all", "I agree", "Agree",
    "Alle akzeptieren", "Aceptar todo", "Tout accepter", "Accetta tutto",
    "قبول الكل", "أوافق", "موافق", "الموافقة على الكل",
]


async def _emit_progress(on_progress, event_type: str, message: str, **extra) -> None:
    if on_progress:
        on_progress({"type": event_type, "message": message, **extra})


def _check_cancel(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel and should_cancel():
        raise ScrapeCancelled()


async def handle_google_consent(page, lang: str = "en") -> bool:
    """Dismiss Google consent / terms interstitial if shown."""
    handled = False
    for attempt in range(4):
        url = page.url or ""
        title = await page.title()
        on_consent_host = "consent.google" in url
        on_consent_title = "consent" in title.lower() or "قبل المتابعة" in title or "Before you continue" in title

        if not on_consent_host and not on_consent_title:
            if attempt == 0:
                return handled
            break

        logger.info("Consent page detected (attempt %s) url=%s title=%s", attempt + 1, url, title)
        clicked = False

        for selector in CONSENT_SELECTORS:
            try:
                loc = page.locator(selector)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click(timeout=4000)
                    clicked = True
                    logger.info("Clicked consent via selector: %s", selector)
                    break
            except Exception as exc:
                logger.debug("Consent selector %s failed: %s", selector, exc)

        if not clicked:
            for name in CONSENT_BUTTON_NAMES:
                try:
                    button = page.get_by_role("button", name=name, exact=False)
                    if await button.count() > 0:
                        await button.first.click(timeout=4000)
                        clicked = True
                        logger.info("Clicked consent via button name: %s", name)
                        break
                except Exception as exc:
                    logger.debug("Consent button name %s failed: %s", name, exc)

        if not clicked:
            try:
                buttons = page.locator("form[action*='consent'] button, form button")
                if await buttons.count() > 0:
                    await buttons.first.click(timeout=4000)
                    clicked = True
                    logger.info("Clicked first consent form button")
            except Exception as exc:
                logger.debug("Consent form button fallback failed: %s", exc)

        if not clicked:
            logger.warning("Could not find consent accept button (lang=%s)", lang)
            break

        handled = True
        await asyncio.sleep(random_delay(1.5, 2.5))
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        await asyncio.sleep(random_delay(1.0, 2.0))

        if "consent.google" not in (page.url or ""):
            logger.info("Consent dismissed — now at %s", page.url)
            return True

    return handled

# --- Helper Functions ---
def create_search_url(query, lang="en", lat=None, lng=None, zoom=None):
    """Creates a Google Maps search URL, optionally centered on lat/lng with zoom."""
    from urllib.parse import quote
    encoded_query = quote(query)
    if lat is not None and lng is not None:
        z = zoom if zoom is not None else 15
        return f"https://www.google.com/maps/search/{encoded_query}/@{lat},{lng},{z}z?hl={lang}"
    params = {'q': query, 'hl': lang}
    return BASE_URL + "?" + urlencode(params)

async def scrape_place_details(context, link, semaphore):
    """
    Scrapes details for a single place using a new page from the browser context.
    Uses a semaphore to limit concurrency.

    Args:
        context: Playwright browser context
        link (str): URL to the place page
        semaphore: asyncio.Semaphore for concurrency control

    Returns:
        dict: Place data dictionary
    """
    async with semaphore:
        page = await context.new_page()
        try:
            logger.info(f"Processing link: {link}")
            await page.goto(link, wait_until='domcontentloaded')

            # Wait for dynamic content to load (rating, reviews, etc.)
            await asyncio.sleep(random_delay(2.0, 3.0))

            html_content = await page.content()
            place_data = extractor.extract_place_data(html_content)

            if place_data:
                place_data['link'] = link
                return place_data
            else:
                logger.warning(f"Failed to extract data for: {link}")
                # Optionally save the HTML for debugging
                # with open(f"error_page_{hash(link)}.html", "w", encoding="utf-8") as f:
                #     f.write(html_content)
                return None

        except PlaywrightTimeoutError:
            logger.warning(f"Timeout navigating to or processing: {link}")
            return None
        except Exception as e:
            logger.error(f"Error processing {link}: {e}")
            return None
        finally:
            await page.close()

# --- Main Scraping Logic ---
async def scrape_google_maps(
    query,
    max_places=None,
    lang="en",
    headless=True,
    concurrency=5,
    lat=None,
    lng=None,
    zoom=15,
    filter_city=None,
    on_progress=None,
    should_cancel=None,
):
    """
    Scrapes Google Maps for places based on a query.

    Args:
        query (str): The search query (e.g., "restaurants in New York").
        max_places (int, optional): Maximum number of places to scrape. Defaults to None (scrape all found).
        lang (str, optional): Language code for Google Maps (e.g., 'en', 'es'). Defaults to "en".
        headless (bool, optional): Whether to run the browser in headless mode. Defaults to True.
        concurrency (int, optional): Number of concurrent tabs for scraping details. Defaults to 5.
        lat (float, optional): Center latitude for geo-targeted search.
        lng (float, optional): Center longitude for geo-targeted search.
        zoom (int, optional): Map zoom level (14-17 recommended for grid cells). Defaults to 15.

    Returns:
        list: A list of dictionaries, each containing details for a scraped place.
              Returns an empty list if no places are found or an error occurs.
    """
    results = []
    place_links = set()
    scroll_attempts_no_new = 0
    browser = None

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    '--disable-dev-shm-usage',  # Use /tmp instead of /dev/shm for shared memory
                    '--no-sandbox',  # Required for running in Docker
                    '--disable-setuid-sandbox',
                ]
            )
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                java_script_enabled=True,
                accept_downloads=False,
                locale=f"{lang}-SA" if lang == "ar" else lang,
                timezone_id="Asia/Riyadh",
                geolocation={"latitude": 24.7136, "longitude": 46.6753},
                permissions=["geolocation"],
            )
            
            # --- Step 1: Navigate to Google Maps and perform search ---
            page = await context.new_page()
            if not page:
                await browser.close()
                raise Exception("Failed to create a new browser page (context.new_page() returned None).")

            # Navigate to search — direct geo URL or homepage + search box
            if lat is not None and lng is not None:
                search_url = create_search_url(query, lang=lang, lat=lat, lng=lng, zoom=zoom)
                logger.info("Navigating to geo search: %s", search_url)
                await _emit_progress(on_progress, "progress", f"فتح خرائط Google — {query}")
                await page.goto(search_url, wait_until='domcontentloaded')
                await asyncio.sleep(random_delay(3.0, 4.0))
            else:
                logger.info("Navigating to Google Maps homepage...")
                await _emit_progress(on_progress, "progress", "فتح صفحة خرائط Google…")
                await page.goto('https://www.google.com/maps', wait_until='domcontentloaded')
                await asyncio.sleep(random_delay(2.0, 3.0))

            logger.info("Checking for consent/terms page...")
            await _emit_progress(on_progress, "progress", "التحقق من صفحة الموافقة…")
            _check_cancel(should_cancel)
            consent_handled = await handle_google_consent(page, lang=lang)
            if consent_handled:
                await _emit_progress(on_progress, "progress", "تم تجاوز صفحة الموافقة ✓")
                await asyncio.sleep(random_delay(2.0, 3.0))

            # --- Search box (skip when using geo URL — query is already in URL) ---
            if lat is None or lng is None:
                logger.info(f"Typing search query: {query}")
                await _emit_progress(on_progress, "progress", f"البحث عن: {query}")
                try:
                    search_box_selectors = [
                        'input[id="searchboxinput"]',
                        'input[name="q"]',
                        'input[role="combobox"]',
                        'input[aria-controls="ucc-0"]',
                        'input[aria-label*="Search"]',
                        'input[aria-label*="بحث"]',
                        'input[aria-label*="suchen"]',
                        'input[placeholder*="Search"]',
                        'input[placeholder*="بحث"]',
                        'input[placeholder*="Suchen"]',
                    ]

                    search_box = None
                    for selector in search_box_selectors:
                        try:
                            search_box_element = await page.wait_for_selector(selector, state='visible', timeout=3000)
                            if search_box_element:
                                search_box = selector
                                logger.debug(f"Found search box with selector: {selector}")
                                break
                        except Exception as e:
                            logger.debug(f"Selector '{selector}' not found: {e}")
                            continue

                    if not search_box:
                        if "consent.google" in (page.url or ""):
                            await _emit_progress(on_progress, "error", "عالق في صفحة موافقة Google — لم يتم العثور على زر القبول")
                        else:
                            await _emit_progress(on_progress, "error", "لم يتم العثور على مربع البحث في خرائط Google")
                        logger.error("Could not find search box on Google Maps")
                        logger.error("Page title: %s", await page.title())
                        logger.error("Page URL: %s", page.url)
                        await browser.close()
                        return []

                    await page.fill(search_box, query)
                    await asyncio.sleep(random_delay(0.5, 1.0))
                    await page.keyboard.press('Enter')
                    logger.info("Search submitted, waiting for results...")
                    await _emit_progress(on_progress, "progress", "تم إرسال البحث — انتظار النتائج…")
                    await asyncio.sleep(random_delay(3.0, 4.0))

                except Exception as e:
                    logger.error(f"Error performing search: {e}")
                    await _emit_progress(on_progress, "error", f"خطأ أثناء البحث: {e}")
                    await browser.close()
                    return []
            else:
                if consent_handled:
                    search_url = create_search_url(query, lang=lang, lat=lat, lng=lng, zoom=zoom)
                    await page.goto(search_url, wait_until='domcontentloaded')
                    await asyncio.sleep(random_delay(2.0, 3.0))
                    await handle_google_consent(page, lang=lang)

            # --- Scrolling and Link Extraction ---
            logger.info("Scrolling to load places...")
            await _emit_progress(on_progress, "progress", "تمرير القائمة لجمع الأماكن…")
            feed_selector = '[role="feed"]'
            found_feed = False

            # Attempt to find feed with fallbacks (from PR #7)
            try:
                await page.wait_for_selector(feed_selector, state='visible', timeout=10000)
                found_feed = True
            except PlaywrightTimeoutError:
                logger.info(f"Primary feed selector '{feed_selector}' not found. Checking fallbacks...")

            if not found_feed:
                # Check if it's a single result page (maps/place/)
                if "/maps/place/" in page.url:
                    logger.info("Detected single place page.")
                    place_links.add(page.url)
                else:
                    # Try to find place links directly (PR #7 fallback)
                    links = await page.locator('a[href*="/maps/place/"]').evaluate_all('elements => elements.map(a => a.href)')
                    if links:
                        logger.info(f"Found {len(links)} place links directly without feed selector.")
                        place_links.update(links)
                        # We won't be able to scroll effectively, but we have visible links
                    else:
                        logger.error("Error: Feed element not found. Page content may be unexpected.")
                        await _emit_progress(on_progress, "error", "لم تُعثر على نتائج — قد تكون صفحة الموافقة أو البحث فارغاً")
                        await browser.close()
                        return []

            if found_feed and await page.locator(feed_selector).count() > 0:
                last_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
                while True:
                    _check_cancel(should_cancel)
                    # Incremental scroll (more reliable than jumping to bottom)
                    await page.evaluate(f'''() => {{
                        const feed = document.querySelector('{feed_selector}');
                        if (feed) feed.scrollTop += Math.max(feed.clientHeight * 0.85, 400);
                    }}''')
                    await asyncio.sleep(random_delay(1.5, 2.5))

                    current_links_list = await page.locator(f'{feed_selector} a[href*="/maps/place/"]').evaluate_all('elements => elements.map(a => a.href)')
                    current_links = set(current_links_list)
                    new_links_found = len(current_links - place_links) > 0
                    place_links.update(current_links)
                    logger.info(f"Found {len(place_links)} unique place links so far...")

                    if max_places is not None and len(place_links) >= max_places:
                        logger.info(f"Reached max_places limit ({max_places}).")
                        place_links = set(list(place_links)[:max_places])
                        break

                    new_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
                    if new_height == last_height:
                        end_marker_xpath = (
                            "//span[contains(text(), \"You've reached the end of the list.\") "
                            "or contains(text(), \"Has llegado al final de la lista\") "
                            "or contains(text(), \"لقد وصلت إلى نهاية القائمة\")]"
                        )
                        if await page.locator(end_marker_xpath).count() > 0:
                            logger.info("Reached the end of the results list.")
                            break
                        if not new_links_found:
                            scroll_attempts_no_new += 1
                            logger.debug(f"Scroll height unchanged and no new links. Attempt {scroll_attempts_no_new}/{MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS}")
                            if scroll_attempts_no_new >= MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS:
                                logger.info("Stopping scroll due to lack of new links.")
                                break
                        else:
                            scroll_attempts_no_new = 0
                    else:
                        last_height = new_height
                        scroll_attempts_no_new = 0

            # Close the search page as we have the links now
            await page.close()

            _check_cancel(should_cancel)

            # --- Step 2: Scraping Individual Places in Parallel ---
            logger.info(f"Scraping details for {len(place_links)} places with concurrency {concurrency}...")
            await _emit_progress(
                on_progress,
                "progress",
                f"جمع تفاصيل {len(place_links)} مكان…",
                found=len(place_links),
            )

            semaphore = asyncio.Semaphore(concurrency)
            tasks = [scrape_place_details(context, link, semaphore)
                     for link in place_links]
            
            # Run tasks and gather results
            scraped_results = await asyncio.gather(*tasks)
            
            # Filter out None results (failed scrapes)
            results = [r for r in scraped_results if r is not None]

            from .validation import filter_places_for_saudi
            results, filter_stats = filter_places_for_saudi(results, city=filter_city)
            if filter_stats.get("filtered_out"):
                logger.info(
                    "Filtered %d invalid/foreign places (kept %d)",
                    filter_stats["filtered_out"],
                    filter_stats["kept_count"],
                )

            await browser.close()

        except ScrapeCancelled:
            logger.info("Scrape cancelled by user")
            raise
        except PlaywrightTimeoutError:
            logger.error("Timeout error during scraping process.")
            raise
        except Exception as e:
            logger.error(f"An error occurred during scraping: {e}", exc_info=True)
            raise
        finally:
            # Ensure browser is closed if an error occurred mid-process
            if browser and browser.is_connected():
                await browser.close()

    logger.info(f"Scraping finished. Found details for {len(results)} places.")
    return results