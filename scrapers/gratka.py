import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class GratkaScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("gratka", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        self.logger.info(f"Scraping Gratka: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        
        # Cookie Consent
        try:
            # Look for common consent buttons
            consent_btn = await page.query_selector("button:has-text('Zgadzam się'), button:has-text('Akceptuję'), .rodo-popup-agree")
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
                
            self.logger.info(f"Gratka Page {current_page}")
            await asyncio.sleep(2) # Wait for content
            
            cards = await page.query_selector_all("a.property-card")
            if not cards:
                self.logger.info("No cards found, stopping.")
                break
                
            self.logger.info(f"Found {len(cards)} offers on Gratka Page {current_page}")
            page_offers = []
            
            for card in cards:
                try:
                    # Link (Card itself is the link)
                    link = await card.get_attribute("href")
                    if not link:
                        link = ""
                    elif not link.startswith("http"):
                        link = f"https://gratka.pl{link}"
                    
                    # Title
                    title_el = await card.query_selector(".property-card__title")
                    title = self.safe_text(await title_el.inner_text()) if title_el else "No Title"
                    
                    # Price
                    # Price
                    # Structure: <div class="price"> 730 000 zł <span>12 000 zł/m2</span></div>
                    # We need the first text node.
                    price_el = await card.query_selector(".property-card__price")
                    if price_el:
                        # Get text of valid text nodes (excluding span children)
                        price_text = await price_el.evaluate("el => Array.from(el.childNodes).filter(node => node.nodeType === 3).map(node => node.textContent).join('').trim()")
                    else:
                        price_text = ""
                    # Price often contains "zł" and maybe per m2 in a span we want to ignore for main price?
                    # The inner_text usually gets all text.
                    # Example: "500 000 zł\n10 000 zł/m2"
                    
                    # Area
                    area_el = await card.query_selector("[data-cy='cardPropertyInfoArea']")
                    area_text = self.safe_text(await area_el.inner_text()) if area_el else ""
                    
                    # Full text for floor/garden
                    text_content = self.safe_text(await card.inner_text())
                    
                    # Price per m2
                    # Often nested in price container or separate
                    price_m2 = ""
                    pm2_match = re.search(r'(\d+[\s\xa0]?\d+)\s*zł/m2', text_content)
                    if pm2_match:
                        price_m2 = pm2_match.group(1).replace(" ", "")
                    
                    # Location
                    loc_el = await card.query_selector(".property-card__location span")
                    location = self.safe_text(await loc_el.inner_text()) if loc_el else "N/A"
                    
                    floor = self.parse_floor(text_content)
                    garden = self.check_garden(text_content)
                    
                    page_offers.append({
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price_text),
                        "area": self.normalize_area(area_text),
                        "price_per_m2": self.normalize_price(price_m2),
                        "location": location,
                        "source": "gratka",
                        "floor": floor,
                        "garden": garden
                    })
                except Exception as e:
                    self.logger.debug(f"Error parsing card: {e}")
                    # pass
            
            all_offers.extend(page_offers)
            
            # Pagination
            try:
                next_btn = await page.query_selector(".pagination__next")
                if next_btn:
                     # Check if it's a link or button, and if not disabled
                     href = await next_btn.get_attribute("href")
                     if href:
                         await next_btn.click()
                         await page.wait_for_load_state("domcontentloaded")
                         current_page += 1
                         await asyncio.sleep(1)
                     else:
                         break
                else:
                    break
            except:
                break
                
        return all_offers
