import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class NieruchomosciOnlineScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("nieruchomosci_online", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        self.logger.info(f"Scraping Nieruchomosci-online: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        
        try:
            # Cookie consent - "OK" button
            # Usually it's a button with text "OK" or specific class
            await page.get_by_text("OK", exact=True).click(timeout=3000)
        except:
            pass
            
        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break
                
            self.logger.info(f"Nieruchomosci-online Page {current_page}")
            # Wait for content
            await asyncio.sleep(2) 
        
            try:
                # Wait for at least one tile
                await page.wait_for_selector(".tile", timeout=10000)
            except:
                self.logger.info("No offers found on this page.")
                break
    
            # Select all offer tiles
            # We exclude 'tile-google-ads' or other non-offer tiles if possible
            results = await page.query_selector_all(".tile")
            
            self.logger.info(f"Found {len(results)} tiles on Nieruchomosci-online Page {current_page}")
            page_offers = []
            
            for card in results:
                try:
                    # Check if it's a real offer (has price, title) or just an ad
                    # Ads often don't have h2.name
                    title_el = await card.query_selector("h2.name a")
                    if not title_el:
                         # Try finding h2.name without a link or generic h2
                         title_el = await card.query_selector("h2.name")
                    
                    if not title_el:
                        # Likely an ad or empty slot
                        continue

                    # Link
                    # If title_el is 'a', get href. If 'h2', look for 'a' inside or parent.
                    link_el = await card.query_selector("h2.name a")
                    link = await link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = "https://gdansk.nieruchomosci-online.pl" + link # Domain might vary, but user gave subdomain
                        # Actually base domain is usually used for relative links, but let's be safe.
                        # Ideally specific scraper logic handles domain. 
                        # nieruchomosci-online.pl uses relative paths usually.
                    
                    title = self.safe_text(await title_el.inner_text())
                    
                    # Price
                    # .primary-display span or .price
                    price_el = await card.query_selector("span.price")
                    if not price_el:
                         price_el = await card.query_selector(".primary-display span")
                    
                    price_text = self.safe_text(await price_el.inner_text()) if price_el else ""

                    # Area
                    area_el = await card.query_selector("span.size") # Based on subagent
                    if not area_el:
                         area_el = await card.query_selector("span.area")
                    
                    area_text = self.safe_text(await area_el.inner_text()) if area_el else ""
                    
                    # Full text for floor/rooms checks
                    text_content = self.safe_text(await card.inner_text())

                    # Price/m2
                    # Often not explicit in a simple selector, usually "X zł/m2" in text
                    # Regex search in text content or specific element
                    pm2_match = re.search(r'(\d+[\s\xa0]?\d+)\s*zł/m²', text_content)
                    price_m2 = pm2_match.group(1).replace(" ", "").replace("\xa0", "") if pm2_match else ""

                    # Location
                    loc_el = await card.query_selector(".province")
                    if not loc_el:
                        loc_el = await card.query_selector("p.province")
                    
                    location = self.safe_text(await loc_el.inner_text()) if loc_el else ""
                    
                    # Debug print to see what we are catching
                    self.logger.debug(f"DEBUG: Scraped {title[:30]}... | Loc: {location} | Area: {area_text} -> {self.normalize_area(area_text)}")

                    # Image
                    # .tile-holder img
                    img_el = await card.query_selector(".tile-holder img")
                    if not img_el:
                         img_el = await card.query_selector(".thumb-slider img")
                    
                    # Logic for floor
                    # Try to find specific floor info in attributes
                    # Often in .attributes-row or similar
                    floor = self.parse_floor(text_content)
                    
                    garden = self.check_garden(text_content)

                    offer = {
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price_text),
                        "area": self.normalize_area(area_text),
                        "price_per_m2": self.normalize_price(price_m2),
                        "location": location,
                        "source": "nieruchomosci-online",
                        "floor": floor,
                        "garden": garden
                    }
                    
                    # Quick fix for duplicated offers or empty scraped data
                    if offer["price"] or offer["area"]:
                        page_offers.append(offer)

                except Exception as e:
                    # Generic error catching per card to not break the loop
                    # self.logger.debug(f"Error parse card: {e}")
                    pass
            
            all_offers.extend(page_offers)
            
            # Pagination
            # Look for "Następna" button
            try:
                next_btn = await page.query_selector("li.next-wrapper a")
                if not next_btn:
                     # Fallback by text
                     next_btn = await page.get_by_text("Następna", exact=True)
                
                if next_btn:
                    # Check if disabled? usually li has class disabled, not a tag.
                    # click it
                    await next_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    current_page += 1
                    await asyncio.sleep(1)
                else:
                    break
            except:
                break
                
        return all_offers
