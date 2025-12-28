import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class SzybkoScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("szybko", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        # Construct URL properly if needed, or assume the caller provides a valid search URL
        # Szybko URL format: https://szybko.pl/l/na-sprzedaz/lokal-mieszkalny/{City}
        # But commonly we might receive a base URL or we constructed it in scraper.py
        # For now, we trust the URL passed in, or if it's just the base, we might need to search.
        # Assuming the standard URL provided by main scraper logic will be used.
        
        self.logger.info(f"Scraping Szybko: {url}")
        await page.goto(url, wait_until="domcontentloaded")

        # Cookie Consent
        try:
            # Common consent buttons including Google Funding Choices (.fc-primary-button)
            consent_btn = await page.query_selector("button:has-text('Zgadzam się'), .fc-primary-button, .rodo-popup-agree")
            if consent_btn:
                await consent_btn.click()
                await asyncio.sleep(1)
        except:
            pass
            
        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break

            self.logger.info(f"Szybko Page {current_page}")
            # Wait for list to load
            try:
                await page.wait_for_selector(".listing-item", timeout=10000)
            except:
                self.logger.info("No listing items found - timed out.")
                break

            cards = await page.query_selector_all(".listing-item")
            if not cards:
                self.logger.info("No cards found, stopping.")
                break
                
            self.logger.info(f"Found {len(cards)} offers on Szybko Page {current_page}")
            page_offers = []
            
            for card in cards:
                try:
                    # Link & Title
                    title_el = await card.query_selector(".listing-title-heading")
                    if not title_el:
                        continue
                        
                    title = self.safe_text(await title_el.inner_text())
                    link = await title_el.get_attribute("href")
                    if link and not link.startswith("http"):
                        link = f"https://szybko.pl{link}"
                    
                    # Price
                    # Structure often: <div class="listing-price">500 000 zł <i>10 000 zł/m²</i></div>
                    price_el = await card.query_selector(".listing-price")
                    price_text = ""
                    price_m2_text = ""
                    
                    if price_el:
                        # raw text might be "500 000 zł 10 000 zł/m²"
                        full_price_text = await price_el.inner_text()
                        # Extract main price (digits before 'zł')
                        # or just pass robustly to normalize_price
                        
                        # Let's try to split or extract if possible, but valid strategy is:
                        # normalize_price takes text and finds numbers. 
                        # If we have "X zł Y zł/m2", normalize might get confused if it grabs all digits.
                        # It usually removes non-digits. So "50000010000". That is bad.
                        
                        # Try to get direct text node for main price
                        # extracting text nodes via evaluation is safer
                        price_text = await price_el.evaluate("el => el.firstChild.textContent")
                        
                        # Price per m2
                        m2_el = await price_el.query_selector("i")
                        if m2_el:
                            price_m2_text = await m2_el.inner_text()
                    
                    # Area
                    # Look for element with 'area' class or similar
                    # Subagent said .asset-feature.area
                    area_el = await card.query_selector(".asset-feature.area")
                    area_text = ""
                    if area_el:
                        area_text = await area_el.inner_text()
                    
                    # Location
                    loc_el = await card.query_selector(".list-elem-address")
                    location = self.safe_text(await loc_el.inner_text()) if loc_el else "N/A"
                    
                    # Description / Features for Floor & Garden
                    # .listing-description-highlight might contain info
                    desc_el = await card.query_selector(".listing-description-highlight")
                    desc_text = self.safe_text(await desc_el.inner_text()) if desc_el else ""
                    
                    # Also check feature bubbles if any (rooms, etc can be used for debugging but not requested)
                    
                    floor = self.parse_floor(desc_text)
                    garden = self.check_garden(desc_text)
                    
                    page_offers.append({
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price_text),
                        "area": self.normalize_area(area_text),
                        "price_per_m2": self.normalize_price(price_m2_text),
                        "location": location,
                        "source": "szybko",
                        "floor": floor,
                        "garden": garden
                    })
                except Exception as e:
                    self.logger.warning(f"Error parsing card: {e}")
            
            all_offers.extend(page_offers)
            
            # Pagination
            # User provided specific element: <a class="next" aria-label="Strona następna" ...>
            try:
                # Aggressively remove overlays before interacting
                await page.evaluate("""
                    () => {
                        const overlays = document.querySelectorAll('.fc-consent-root, .fc-dialog-overlay, .rodo-popup');
                        overlays.forEach(el => el.remove());
                    }
                """)
                
                # Use strict selector as requested/verified
                next_btn = await page.query_selector("a.next[aria-label='Strona następna']")
                
                if next_btn:
                     href = await next_btn.get_attribute("href")
                     if href:
                         # Click and wait for navigation or content update
                         # Force click to bypass overlays
                         await next_btn.click(force=True)
                         # Szybko seems to do a full page load usually
                         await page.wait_for_load_state("domcontentloaded")
                         current_page += 1
                         await asyncio.sleep(2)
                     else:
                         self.logger.info("Next button has no href, stopping.")
                         break
                else:
                    self.logger.info("No next button found.")
                    break
            except Exception as e:
                self.logger.info(f"Pagination error or end: {e}")
                break
                
        return all_offers
