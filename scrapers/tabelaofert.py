import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class TabelaofertScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("tabelaofert", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        self.logger.info(f"Scraping Tabelaofert: {url}")
        
        # Build URL with filters if not already present
        # Note: scraper.py calls build_url which we will update later
        # For now, let's assume the URL is already prepared or we handle it here if it's a base URL
        
        await page.goto(url, wait_until="domcontentloaded")
        
        # Accept cookies
        try:
            # Often it's an overlay or specific button
            await page.click("button#onetrust-accept-btn-handler", timeout=3000)
        except:
            pass
            
        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break
                
            self.logger.info(f"Tabelaofert Page {current_page}")
            # Wait for dynamic content (React)
            await asyncio.sleep(2)

            # Selector for offer cards based on subagent research
            cards = await page.query_selector_all('div[class*="Oferta-module-scss-module__D3hq-q__oferta"]')
            
            if not cards:
                # Fallback if class changes slightly
                cards = await page.query_selector_all('div[class*="Oferta-module"]')
            
            if not cards:
                self.logger.warning("No offers found on page.")
                break

            page_offers = []
            for card in cards:
                try:
                    # Extracts using identified selectors
                    title_el = await card.query_selector('a[class*="OfertaNazwa-module-scss-module__lEAnAW__link"] h3')
                    link_el = await card.query_selector('a[class*="OfertaNazwa-module-scss-module__lEAnAW__link"]')
                    price_el = await card.query_selector('div[class*="OfertaCena-module-scss-module__38hH9S__cena"]')
                    area_el = await card.query_selector('div[class*="Metraz-module-scss-module__nEYmRG__metraz"]')
                    loc_el = await card.query_selector('div[class*="OfertaLokalizacja-module-scss-module__"]')

                    title = self.safe_text(await title_el.inner_text()) if title_el else "Tabelaofert Offer"
                    link = await link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = "https://tabelaofert.pl" + link
                    
                    price_text = await price_el.inner_text() if price_el else ""
                    area_text = await area_el.inner_text() if area_el else ""
                    location = self.safe_text(await loc_el.inner_text()) if loc_el else "N/A"

                    # Normalize
                    price = self.normalize_price(price_text)
                    area = self.normalize_area(area_text)
                    
                    # Area matches "50.5 m²" usually, normalize_area handles m2/m²
                    
                    # Extract floor/garden from text if available 
                    # Usually Tabelaofert has icons or specific text for these items
                    full_text = await card.inner_text()
                    floor = self.parse_floor(full_text)
                    garden = self.check_garden(full_text)

                    if link:
                        page_offers.append({
                            "url": link,
                            "title": title,
                            "price": price,
                            "area": area,
                            "price_per_m2": round(price / area, 2) if price and area else None,
                            "location": location,
                            "source": "tabelaofert",
                            "floor": floor,
                            "garden": garden
                        })
                except Exception as e:
                    self.logger.debug(f"Error parsing card: {e}")
            
            all_offers.extend(page_offers)
            
            # Pagination
            try:
                # Selector identified: div[class*="Paginacja-module"] a[class*="next"]
                next_btn = await page.query_selector('div[class*="Paginacja-module"] a[class*="next"]')
                if not next_btn:
                    # Fallback to last arrow or text "Następna"
                    next_btn = await page.query_selector('ul[class*="paginacja"] li:last-child a')
                
                if next_btn:
                    is_disabled = await next_btn.get_attribute("disabled")
                    if is_disabled:
                        break
                        
                    await next_btn.click()
                    current_page += 1
                else:
                    break
            except:
                break
                
        return all_offers
