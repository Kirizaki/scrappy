import asyncio
from .base import BaseScraper
from playwright.async_api import Page

class GethomeScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("gethome", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        self.logger.info(f"Scraping Gethome: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        
        # Cookie Consent - Cookiebot
        try:
            # Button often has ID: #CybotCookiebotDialogBodyLevelButtonLevelOptinAllowall
            consent_btn = await page.query_selector("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowall")
            if consent_btn:
                await consent_btn.click()
                await asyncio.sleep(1)
        except Exception as e:
            self.logger.debug(f"Cookie consent handling skipped: {e}")

        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break
            
            self.logger.info(f"Gethome Page {current_page}")
            
            # Wait for offers list
            try:
                # Offer link class from research
                await page.wait_for_selector("a.o13k6g1y", timeout=10000)
            except:
                self.logger.info("No listing items found - timed out.")
                break

            # Find all offer containers
            # Research: Offer Container is li containing a.o13k6g1y
            cards = await page.query_selector_all("li:has(a.o13k6g1y)")
            
            if not cards:
                 self.logger.info("No cards found.")
                 break
            
            self.logger.info(f"Found {len(cards)} offers on Gethome Page {current_page}")
            page_offers = []
            
            for card in cards:
                try:
                    # Link
                    link_el = await card.query_selector("a.o13k6g1y")
                    if not link_el: continue
                    
                    link = await link_el.get_attribute("href")
                    if link and not link.startswith("http"):
                        link = f"https://gethome.pl{link}"
                        
                    # Title
                    title_el = await card.query_selector('[data-testid="header-offerbox"]')
                    title = await title_el.inner_text() if title_el else "N/A"
                    
                    # Price
                    price_el = await card.query_selector(".o1bbpdyd")
                    price_text = await price_el.inner_text() if price_el else ""
                    
                    # Area
                    # Selector excludes testid (rooms)
                    area_el = await card.query_selector(".ngl9ymk:not([data-testid])")
                    area_text = await area_el.inner_text() if area_el else ""
                    
                    # Location
                    loc_el = await card.query_selector("address")
                    location = await loc_el.inner_text() if loc_el else "N/A"
                    
                    # Garden/Floor checks could be added if we inspect description or attributes
                    # For now, default parsing
                    
                    page_offers.append({
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price_text),
                        "area": self.normalize_area(area_text),
                        "price_per_m2": 0.0, # Not easily available in list view
                        "location": location,
                        "source": "gethome"
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Error parsing Gethome card: {e}")
            
            all_offers.extend(page_offers)
            
            # Pagination
            if max_pages > 0 and current_page >= max_pages:
                 break
                 
            # Next button: a.gh-kuabcj.e134q4pk2
            try:
                # Aggressively remove overlays before interacting
                await page.evaluate("""
                    () => {
                        const overlays = document.querySelectorAll('#CybotCookiebotDialog, #CybotCookiebotDialogBodyUnderlay');
                        overlays.forEach(el => el.remove());
                    }
                """)
                
                next_btn = await page.query_selector("a.gh-kuabcj.e134q4pk2")
                if next_btn:
                    href = await next_btn.get_attribute("href")
                    if href:
                        await next_btn.click(force=True)
                        await page.wait_for_load_state("domcontentloaded")
                        current_page += 1
                        await asyncio.sleep(2)
                    else:
                        break
                else:
                    self.logger.info("No next button found.")
                    break
            except Exception as e:
                self.logger.info(f"Pagination done/error: {e}")
                break
                
        return all_offers
