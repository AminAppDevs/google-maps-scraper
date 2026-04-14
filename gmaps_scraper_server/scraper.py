import json
import asyncio
import re
import random
import logging
import os
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urlencode

# Import the extraction functions from our helper module
from . import extractor

# --- Logging Configuration ---
logger = logging.getLogger(__name__)

# --- Constants ---
BASE_URL = "https://www.google.com/maps/search/"
DEFAULT_TIMEOUT = 30000  # 30 seconds for navigation and selectors
SCROLL_PAUSE_TIME = 1.5  # Pause between scrolls
MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS = 5 # Stop scrolling if no new links found after this many scrolls

# User agent rotation for anti-detection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def random_delay(min_sec=1.0, max_sec=2.0):
    """Returns random delay for anti-detection"""
    return random.uniform(min_sec, max_sec)

# --- Helper Functions ---
def create_search_url(query, lang="en", geo_coordinates=None, zoom=None):
    """Creates a Google Maps search URL."""
    params = {'q': query, 'hl': lang}
    # Note: geo_coordinates and zoom might require different URL structure (/maps/@lat,lng,zoom)
    # For simplicity, starting with basic query search
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
async def scrape_google_maps(query, max_places=None, lang="en", headless=True, concurrency=5):
    """
    Scrapes Google Maps for places based on a query.

    Args:
        query (str): The search query (e.g., "restaurants in New York").
        max_places (int, optional): Maximum number of places to scrape. Defaults to None (scrape all found).
        lang (str, optional): Language code for Google Maps (e.g., 'en', 'es'). Defaults to "en".
        headless (bool, optional): Whether to run the browser in headless mode. Defaults to True.
        concurrency (int, optional): Number of concurrent tabs for scraping details. Defaults to 5.

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
                user_agent=random.choice(USER_AGENTS),  # Random user agent for anti-detection
                java_script_enabled=True,
                accept_downloads=False,
                locale=lang,
            )
            
            # --- Step 1: Navigate to Google Maps and perform search ---
            page = await context.new_page()
            if not page:
                await browser.close()
                raise Exception("Failed to create a new browser page (context.new_page() returned None).")

            # Navigate to Google Maps homepage first (more natural, avoids sidebar issues)
            logger.info("Navigating to Google Maps homepage...")
            await page.goto('https://www.google.com/maps', wait_until='domcontentloaded')
            await asyncio.sleep(random_delay(2.0, 3.0))  # Give page time to fully load

            # --- Handle Terms of Service / Consent pages BEFORE search ---
            # Google Maps may show a consent page before showing the actual map
            logger.info("Checking for consent/terms page...")
            consent_handled = False
            
            try:
                # Check if we're on a consent page by looking for consent-related elements
                # German: "Alle akzeptieren", "Alle ablehnen"
                # English: "Accept all", "Reject all", "I agree", "I reject"
                # Spanish: "Aceptar todo", "Rechazar todo"
                # French: "Tout accepter", "Tout refuser"
                # Italian: "Accetta tutto", "Rifiuta tutto"
                # Dutch: "Alles accepteren", "Alles afwijzen"
                # Portuguese: "Aceitar tudo", "Recusar tudo"
                # Polish: "Zaakceptuj wszystko", "Odrzuć wszystko"
                # Swedish: "Godkänn alla", "Avvisa alla"
                # Danish: "Acceptér alle", "Afvis alle"
                # Norwegian: "Godta alle", "Avvis alle"
                # Greek: "Αποδοχή όλων", "Απόρριψη όλων"
                # Turkish: "Tümünü kabul et", "Tümünü reddet"
                
                # Use aria-label selectors instead of XPath (XPath text() matching is unreliable)
                consent_selectors = [
                    # German
                    'button[aria-label="Alle akzeptieren"]',  # German accept
                    'button[aria-label="Alle ablehnen"]',     # German reject
                    # English
                    'button[aria-label="I agree"]',           # English accept
                    'button[aria-label="I reject"]',          # English reject
                    'button[aria-label="Accept all"]',        # English accept
                    'button[aria-label="Reject all"]',        # English reject
                    # Spanish
                    'button[aria-label="Aceptar todo"]',      # Spanish accept
                    'button[aria-label="Rechazar todo"]',     # Spanish reject
                    # French (correct order: "Tout accepter", "Tout refuser")
                    'button[aria-label="Tout accepter"]',     # French accept
                    'button[aria-label="Tout refuser"]',      # French reject
                    # Italian
                    'button[aria-label="Accetta tutto"]',     # Italian accept
                    'button[aria-label="Rifiuta tutto"]',     # Italian reject
                    # Dutch
                    'button[aria-label="Alles accepteren"]',  # Dutch accept
                    'button[aria-label="Alles afwijzen"]',    # Dutch reject
                    # Portuguese
                    'button[aria-label="Aceitar tudo"]',      # Portuguese accept
                    'button[aria-label="Recusar tudo"]',      # Portuguese reject
                    # Polish
                    'button[aria-label="Zaakceptuj wszystko"]', # Polish accept
                    'button[aria-label="Odrzuć wszystko"]',    # Polish reject
                    # Swedish
                    'button[aria-label="Godkänn alla"]',      # Swedish accept
                    'button[aria-label="Avvisa alla"]',       # Swedish reject
                    # Danish
                    'button[aria-label="Acceptér alle"]',     # Danish accept
                    'button[aria-label="Afvis alle"]',        # Danish reject
                    # Norwegian
                    'button[aria-label="Godta alle"]',        # Norwegian accept
                    'button[aria-label="Avvis alle"]',        # Norwegian reject
                    # Greek
                    'button[aria-label="Αποδοχή όλων"]',      # Greek accept
                    'button[aria-label="Απόρριψη όλων"]',     # Greek reject
                    # Turkish
                    'button[aria-label="Tümünü kabul et"]',   # Turkish accept
                    'button[aria-label="Tümünü reddet"]',     # Turkish reject
                ]
                
                consent_button = None
                for selector in consent_selectors:
                    try:
                        consent_button = await page.wait_for_selector(selector, state='visible', timeout=3000)
                        if consent_button:
                            logger.info(f"Found consent page - clicking accept/reject button with selector: {selector}")
                            await consent_button.click()
                            consent_handled = True
                            await asyncio.sleep(random_delay(1.0, 2.0))  # Wait for navigation
                            break
                    except Exception as e:
                        logger.debug(f"Selector '{selector}' not found: {e}")
                        continue
                    
            except PlaywrightTimeoutError:
                logger.debug("No consent page detected or timed out waiting.")
            except Exception as e:
                logger.warning(f"Error handling consent page: {e}")
            
            # If consent was handled, wait for the page to stabilize
            if consent_handled:
                await asyncio.sleep(random_delay(2.0, 3.0))

            # --- Find and use the search box AFTER consent handling ---
            logger.info(f"Typing search query: {query}")
            try:
                # Updated search box selectors for new Google Maps DOM structure
                # The input element uses role="combobox" and name="q"
                search_box_selectors = [
                    'input[name="q"]',  # PRIMARY: Most reliable selector
                    'input[role="combobox"]',  # SECONDARY: Combobox role
                    'input[aria-controls="ucc-0"]',  # TERTIARY: Control attribute
                    'input[id="searchboxinput"]',  # FALLBACK: Older selector
                    'input[aria-label*="Search"]',  # FALLBACK: English
                    'input[aria-label*="suchen"]',  # FALLBACK: German
                    'input[placeholder*="Search"]',  # FALLBACK
                    'input[placeholder*="Suchen"]',  # FALLBACK: German
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
                    # Additional diagnostic: log what elements exist on the page
                    logger.error("Could not find search box on Google Maps")
                    logger.error("Page title: %s", await page.title())
                    logger.error("Page URL: %s", page.url)
                    
                    # Try to debug: find all input elements on the page
                    try:
                        all_inputs = await page.query_selector_all('input')
                        logger.error(f"Found {len(all_inputs)} input elements on the page")
                        for i, inp in enumerate(all_inputs[:5]):
                            attrs = await inp.get_attribute('name'), await inp.get_attribute('aria-label'), await inp.get_attribute('placeholder')
                            logger.error(f"Input {i}: name={attrs[0]}, aria-label={attrs[1]}, placeholder={attrs[2]}")
                    except Exception as debug_error:
                        logger.error(f"Could not debug input elements: {debug_error}")
                    
                    await browser.close()
                    return []

                # Type the query into the search box
                await page.fill(search_box, query)
                await asyncio.sleep(random_delay(0.5, 1.0))

                # Press Enter to submit search
                await page.keyboard.press('Enter')
                logger.info("Search submitted, waiting for results...")
                await asyncio.sleep(random_delay(3.0, 4.0))

            except Exception as e:
                logger.error(f"Error performing search: {e}")
                await browser.close()
                return []


            # --- Scrolling and Link Extraction ---
            logger.info("Scrolling to load places...")
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
                        logger.error(f"Error: Feed element not found. Page content may be unexpected.")
                        await browser.close()
                        return []

            if found_feed and await page.locator(feed_selector).count() > 0:
                last_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
                while True:
                    # Scroll down
                    await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollTop = document.querySelector(\'{feed_selector}\').scrollHeight')
                    await asyncio.sleep(random_delay(1.0, 2.0))  # Random delay for anti-detection

                    # Extract links after scroll
                    current_links_list = await page.locator(f'{feed_selector} a[href*="/maps/place/"]').evaluate_all('elements => elements.map(a => a.href)')
                    current_links = set(current_links_list)
                    new_links_found = len(current_links - place_links) > 0
                    place_links.update(current_links)
                    logger.info(f"Found {len(place_links)} unique place links so far...")

                    if max_places is not None and len(place_links) >= max_places:
                        logger.info(f"Reached max_places limit ({max_places}).")
                        place_links = set(list(place_links)[:max_places]) # Trim excess links
                        break

                    # Check if scroll height has changed
                    new_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
                    if new_height == last_height:
                        # Check for the "end of results" marker
                        # Check for end marker in multiple languages (PR #7)
                        end_marker_xpath = "//span[contains(text(), \"You've reached the end of the list.\") or contains(text(), \"Has llegado al final de la lista\")]"
                        if await page.locator(end_marker_xpath).count() > 0:
                            logger.info("Reached the end of the results list.")
                            break
                        else:
                            # If height didn't change but end marker isn't there, maybe loading issue?
                            if not new_links_found:
                                scroll_attempts_no_new += 1
                                logger.debug(f"Scroll height unchanged and no new links. Attempt {scroll_attempts_no_new}/{MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS}")
                                if scroll_attempts_no_new >= MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS:
                                    logger.info("Stopping scroll due to lack of new links.")
                                    break
                            else:
                                scroll_attempts_no_new = 0 # Reset if new links were found this cycle
                    else:
                        last_height = new_height
                        scroll_attempts_no_new = 0 # Reset if scroll height changed

            # Close the search page as we have the links now
            await page.close()

            # --- Step 2: Scraping Individual Places in Parallel ---
            logger.info(f"Scraping details for {len(place_links)} places with concurrency {concurrency}...")

            semaphore = asyncio.Semaphore(concurrency)
            tasks = [scrape_place_details(context, link, semaphore)
                     for link in place_links]
            
            # Run tasks and gather results
            scraped_results = await asyncio.gather(*tasks)
            
            # Filter out None results (failed scrapes)
            results = [r for r in scraped_results if r is not None]

            await browser.close()

        except PlaywrightTimeoutError:
            logger.error(f"Timeout error during scraping process.")
        except Exception as e:
            logger.error(f"An error occurred during scraping: {e}", exc_info=True)
        finally:
            # Ensure browser is closed if an error occurred mid-process
            if browser and browser.is_connected():
                await browser.close()

    logger.info(f"Scraping finished. Found details for {len(results)} places.")
    return results